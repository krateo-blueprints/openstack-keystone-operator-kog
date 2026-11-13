#!/usr/bin/env python3
"""Keystone-auth reverse proxy for an OpenStack service API.

The KOG rest-dynamic-controller speaks plain HTTP and cannot do Keystone token
exchange/refresh. This proxy authenticates with OpenStack credentials, discovers
the target service endpoint from the catalog (SERVICE_TYPE), and forwards every
request with a fresh X-Auth-Token (keystoneauth refreshes it automatically). The
operator's OAS `servers[0].url` points at this proxy instead of the service.

Credentials are files, re-read while running, so a rotated Secret is picked up
without a restart:
  - CRED_DIR set: a directory of OS_* files (a Secret of OS_* variables mounted as
    a volume, e.g. the OpenStack blueprint's keystone-keystone-admin), used through
    openstacksdk's `envvars` cloud;
  - otherwise: the clouds.yaml at OS_CLIENT_CONFIG_FILE.
Before each request the proxy fingerprints the credentials and rebuilds its
session when they changed. When Keystone rejects them, the proxy stops asking:
until the credentials change it answers 503 without contacting Keystone, retrying
the same credentials at most once every CREDENTIAL_RETRY_SECONDS. (Calling
Keystone with a known-bad password every few seconds is what locks an account.)

Two local endpoints never reach the upstream:
  /_bridge/ready  200 once the proxy is serving - the readiness probe. It does
                  not depend on Keystone accepting the credentials, so an identity
                  failure stays visible as one instead of emptying the Service.
  /_bridge/auth   200 when the current credentials yield a token, 503 when they
                  do not (JSON: state, error, credentials fingerprint prefix).

Env:
  OS_CLOUD                  cloud name (default: openstack; `envvars` with CRED_DIR)
  CRED_DIR                  directory of OS_* credential files (optional)
  OS_CLIENT_CONFIG_FILE     clouds.yaml path (used when CRED_DIR is unset)
  SERVICE_TYPE              catalog service type to proxy (default: identity)
  OS_INTERFACE              endpoint interface (default: internal)
  UPSTREAM_ENDPOINT         override the discovered endpoint (optional)
  MICROVERSION_HEADER       header name to inject a default microversion under (optional)
  MICROVERSION              default microversion value (used only with MICROVERSION_HEADER)
  CREDENTIAL_RETRY_SECONDS  retry period for credentials Keystone rejected (default 300)
  LISTEN_PORT               default 8080
"""
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openstack
from keystoneauth1 import exceptions as ksa_exc

CLOUD = os.environ.get("OS_CLOUD", "openstack")
CRED_DIR = os.environ.get("CRED_DIR", "")
CLOUDS_FILE = os.environ.get("OS_CLIENT_CONFIG_FILE", "")
SERVICE_TYPE = os.environ.get("SERVICE_TYPE", "identity")
INTERFACE = os.environ.get("OS_INTERFACE", "internal")
MV_HEADER = os.environ.get("MICROVERSION_HEADER", "")
MV = os.environ.get("MICROVERSION", "")
RETRY_SECONDS = float(os.environ.get("CREDENTIAL_RETRY_SECONDS", "300"))
PORT = int(os.environ.get("LISTEN_PORT", "8080"))

# Variables the Deployment sets explicitly win over same-named credential files (as `env` won over
# `envFrom` before), and are never removed when a file disappears.
_BASE_ENV = frozenset(k for k in os.environ if k.startswith("OS_"))
_HOP = {"content-length", "transfer-encoding", "content-encoding", "connection", "keep-alive"}


def log(msg):
    print(f"[proxy] {msg}", flush=True)


class CredentialsRejected(Exception):
    """Keystone refused the current credentials; do not ask again until they change."""


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.session = None
        self.endpoint = None
        self.loaded_fp = None   # fingerprint the current session was built from
        self.applied = set()    # OS_* keys this process put into os.environ from files
        self.failed_fp = None   # fingerprint Keystone rejected
        self.failed_at = 0.0
        self.error = None
        self.state = "unknown"  # unknown | ok | rejected | error

    # -- credentials ---------------------------------------------------------------------------
    def read_credentials(self):
        """-> (fingerprint, {OS_*: value} or None). Re-read on every call (small files)."""
        h = hashlib.sha256()
        if CRED_DIR:
            env = {}
            for name in sorted(os.listdir(CRED_DIR)):
                # A Secret volume holds KEY -> ..data/KEY symlinks plus ..data/..<timestamp> dirs.
                if not name.startswith("OS_"):
                    continue
                path = os.path.join(CRED_DIR, name)
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    env[name] = f.read()
                h.update(name.encode() + b"\0" + env[name].encode() + b"\0")
            return h.hexdigest(), env
        with open(CLOUDS_FILE, "rb") as f:
            h.update(f.read())
        return h.hexdigest(), None

    def _apply_env(self, env):
        for k in self.applied - set(env):
            os.environ.pop(k, None)
        self.applied = set()
        for k, v in env.items():
            if k not in _BASE_ENV:
                os.environ[k] = v
                self.applied.add(k)

    def _build(self, fp, env):
        if env is not None:
            self._apply_env(env)
        conn = openstack.connect(cloud=CLOUD)
        sess = conn.session
        endpoint = os.environ.get("UPSTREAM_ENDPOINT") or sess.get_endpoint(
            service_type=SERVICE_TYPE, interface=INTERFACE)
        self.session, self.endpoint, self.loaded_fp = sess, endpoint.rstrip("/"), fp
        log(f"session built cloud={CLOUD} service={SERVICE_TYPE} endpoint={self.endpoint} credentials={fp[:12]}")

    def current(self):
        """-> (session, endpoint) for the current credentials, or raise CredentialsRejected."""
        fp, env = self.read_credentials()
        with self.lock:
            if fp == self.failed_fp and time.monotonic() - self.failed_at < RETRY_SECONDS:
                raise CredentialsRejected(self.error)
            if self.session is None or fp != self.loaded_fp:
                if self.loaded_fp is not None and fp != self.loaded_fp:
                    log(f"credentials changed ({self.loaded_fp[:12]} -> {fp[:12]}); rebuilding the session")
                self.session = None
                try:
                    self._build(fp, env)   # endpoint discovery authenticates
                except ksa_exc.Unauthorized as exc:
                    self._rejected(fp, exc)
                    raise CredentialsRejected(self.error) from exc
            return self.session, self.endpoint

    def _rejected(self, fp, exc):
        first = self.state != "rejected" or fp != self.failed_fp
        self.failed_fp, self.failed_at = fp, time.monotonic()
        self.error = f"Keystone rejected the credentials ({type(exc).__name__}: {exc})"
        self.state, self.session = "rejected", None
        if first:
            log(f"AUTH REJECTED credentials={fp[:12]}: {exc}. Not retrying them for {RETRY_SECONDS:.0f}s, "
                "or until the credentials change.")

    def rejected(self, exc):
        with self.lock:
            self._rejected(self.loaded_fp or "", exc)

    def ok(self):
        with self.lock:
            if self.state != "ok":
                log(f"auth ok credentials={(self.loaded_fp or '')[:12]}")
            self.state, self.error, self.failed_fp = "ok", None, None

    def errored(self, exc):
        with self.lock:
            self.state, self.error = "error", f"{type(exc).__name__}: {exc}"

    def auth_status(self):
        """Obtain a token with the current credentials (honouring the retry period)."""
        try:
            sess, _ = self.current()
            sess.get_token()
            self.ok()
        except CredentialsRejected:
            pass
        except ksa_exc.Unauthorized as exc:
            self.rejected(exc)
        except Exception as exc:  # network, catalog, file errors
            self.errored(exc)
        with self.lock:
            return {"state": self.state, "error": self.error,
                    "credentials": (self.loaded_fp or self.failed_fp or "")[:12]}


BRIDGE = Bridge()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read_body(self):
        # The Go rest-dynamic-controller sends write bodies with
        # Transfer-Encoding: chunked (no Content-Length); de-chunk explicitly,
        # otherwise the body is dropped and leftover chunk bytes corrupt the
        # keep-alive connection.
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            chunks = []
            while True:
                size_line = self.rfile.readline().split(b";", 1)[0].strip()
                if not size_line:
                    continue
                size = int(size_line, 16)
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else None

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _local(self):
        path = self.path.split("?", 1)[0]
        if path == "/_bridge/ready":
            self._send_json(200, {"ready": True})
            return True
        if path == "/_bridge/auth":
            st = BRIDGE.auth_status()
            self._send_json(200 if st["state"] == "ok" else 503, st)
            return True
        return False

    def _upstream(self, sess, endpoint, body):
        headers = {"Accept": "application/json"}
        if MV_HEADER:
            headers[MV_HEADER] = self.headers.get(MV_HEADER, MV)
        ct = self.headers.get("Content-Type")
        if ct:
            headers["Content-Type"] = ct
        # sess.request injects (and refreshes) X-Auth-Token automatically.
        return sess.request(endpoint + self.path, self.command, headers=headers, data=body, raise_exc=False)

    def _proxy(self):
        if self._local():
            return
        try:
            body = self._read_body()
            sess, endpoint = BRIDGE.current()
            r = self._upstream(sess, endpoint, body)
            if r.status_code == 401:
                # The token was revoked (e.g. the password was reset): drop it and authenticate again
                # once. If the credentials are now wrong, that re-authentication raises Unauthorized.
                sess.invalidate()
                r = self._upstream(sess, endpoint, body)
            BRIDGE.ok()
            data = r.content or b""
            self.send_response(r.status_code)
            for k, v in r.headers.items():
                if k.lower() not in _HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)
        except CredentialsRejected as exc:
            self._send_json(503, {"error_message": f"auth-bridge: {exc}. Waiting for the credentials to change "
                                                   f"(retrying the same ones every {RETRY_SECONDS:.0f}s)."})
        except ksa_exc.Unauthorized as exc:
            BRIDGE.rejected(exc)
            self._send_json(503, {"error_message": f"auth-bridge: {BRIDGE.error}"})
        except Exception as exc:
            BRIDGE.errored(exc)
            self._send_json(502, {"error_message": f"proxy error: {exc}"})
            print(f"[proxy] ERROR {self.command} {self.path}: {exc}", file=sys.stderr, flush=True)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _proxy

    def log_message(self, fmt, *args):
        print("[proxy] " + (fmt % args), flush=True)


if __name__ == "__main__":
    if not CRED_DIR and not CLOUDS_FILE:
        sys.exit("[proxy] set CRED_DIR (OS_* files) or OS_CLIENT_CONFIG_FILE (clouds.yaml)")
    log(f"listening on :{PORT} cloud={CLOUD} credentials={'dir ' + CRED_DIR if CRED_DIR else 'file ' + CLOUDS_FILE}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
