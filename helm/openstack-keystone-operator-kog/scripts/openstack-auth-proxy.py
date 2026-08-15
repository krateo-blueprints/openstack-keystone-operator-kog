#!/usr/bin/env python3
"""Keystone-auth reverse proxy for an OpenStack service API.

The KOG rest-dynamic-controller speaks plain HTTP and cannot do Keystone token
exchange/refresh. This proxy authenticates with clouds.yaml (OS_CLOUD), discovers
the target service endpoint from the catalog (SERVICE_TYPE), and forwards every
request with a fresh X-Auth-Token (keystoneauth refreshes it automatically). The
operator's OAS `servers[0].url` points at this proxy instead of the service.

Generalised from the per-service proxies: SERVICE_TYPE selects the catalog entry
(default `identity` for Keystone), and an optional microversion header can be
injected for services that require one (Nova/Ironic); Keystone needs none.

Env:
  OS_CLOUD             cloud name in clouds.yaml (default: openstack)
  SERVICE_TYPE         catalog service type to proxy (default: identity)
  OS_INTERFACE         endpoint interface (default: internal)
  UPSTREAM_ENDPOINT    override the discovered endpoint (optional)
  MICROVERSION_HEADER  header name to inject a default microversion under (optional)
  MICROVERSION         default microversion value (used only with MICROVERSION_HEADER)
  LISTEN_PORT          default 8080
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openstack

CLOUD = os.environ.get("OS_CLOUD", "openstack")
SERVICE_TYPE = os.environ.get("SERVICE_TYPE", "identity")
INTERFACE = os.environ.get("OS_INTERFACE", "internal")
MV_HEADER = os.environ.get("MICROVERSION_HEADER", "")
MV = os.environ.get("MICROVERSION", "")
PORT = int(os.environ.get("LISTEN_PORT", "8080"))

conn = openstack.connect(cloud=CLOUD)
SESS = conn.session
ENDPOINT = os.environ.get("UPSTREAM_ENDPOINT") or SESS.get_endpoint(
    service_type=SERVICE_TYPE, interface=INTERFACE
)
ENDPOINT = ENDPOINT.rstrip("/")
print(f"[proxy] cloud={CLOUD} service={SERVICE_TYPE} endpoint={ENDPOINT}", flush=True)

_HOP = {"content-length", "transfer-encoding", "content-encoding", "connection", "keep-alive"}


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

    def _proxy(self):
        try:
            body = self._read_body()
            url = ENDPOINT + self.path
            headers = {"Accept": "application/json"}
            if MV_HEADER:
                headers[MV_HEADER] = self.headers.get(MV_HEADER, MV)
            ct = self.headers.get("Content-Type")
            if ct:
                headers["Content-Type"] = ct
            # SESS.request injects (and refreshes) X-Auth-Token automatically.
            r = SESS.request(url, self.command, headers=headers, data=body, raise_exc=False)
            data = r.content or b""
            self.send_response(r.status_code)
            for k, v in r.headers.items():
                if k.lower() not in _HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)
        except Exception as exc:
            msg = f'{{"error_message": "proxy error: {exc}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            print(f"[proxy] ERROR {self.command} {self.path}: {exc}", file=sys.stderr, flush=True)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _proxy

    def log_message(self, fmt, *args):
        print("[proxy] " + (fmt % args), flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
