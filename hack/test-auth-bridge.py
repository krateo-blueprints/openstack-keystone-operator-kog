#!/usr/bin/env python3
"""Behaviour test for the auth-bridge (helm/.../scripts/openstack-auth-proxy.py) against a fake Keystone.

Runs the real script as a subprocess (needs openstacksdk in the interpreter given by $PYTHON, default
this one) in front of an in-process fake Keystone whose admin password can be rotated, and asserts:

  1. readiness (/_bridge/ready) never depends on Keystone accepting the credentials;
  2. a password rotation that revokes tokens is answered with 503 + a clear error, after exactly ONE
     failed authentication - further requests do not reach Keystone (no lockout hammering) until the
     retry period passes, then exactly one retry;
  3. when the credential files change (a rotated Secret, as the kubelet updates a mounted volume), the
     next request rebuilds the session and succeeds, with no restart;
  4. /_bridge/auth reports ok / rejected;
  5. the same for clouds.yaml credentials, starting with a wrong password (the bridge must still start).
Exit 0 = all green.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "helm", "openstack-keystone-operator-kog", "scripts", "openstack-auth-proxy.py")
PYTHON = os.environ.get("PYTHON", sys.executable)
FAILS = []


def check(desc, cond, got=None):
    print(("  ok   " if cond else "  FAIL ") + desc + ("" if cond or got is None else f"   (got: {got})"))
    if not cond:
        FAILS.append(desc)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakeKeystone:
    def __init__(self):
        self.password = "p1"
        self.tokens = set()
        self.ok_auths = 0
        self.failed_auths = 0
        self.n = 0
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        ks = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def send(self, code, obj, headers=None):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def version(self):
                return {"id": "v3.14", "status": "stable", "updated": "2020-04-07T00:00:00Z",
                        "links": [{"rel": "self", "href": ks.base + "/v3/"}],
                        "media-types": [{"base": "application/json",
                                         "type": "application/vnd.openstack.identity-v3+json"}]}

            def do_GET(self):
                path = self.path.split("?")[0].rstrip("/")
                if path == "":
                    return self.send(300, {"versions": {"values": [self.version()]}})
                if path == "/v3":
                    return self.send(200, {"version": self.version()})
                if self.headers.get("X-Auth-Token") not in ks.tokens:
                    return self.send(401, {"error": {"code": 401, "title": "Unauthorized",
                                                     "message": "The request you have made requires authentication."}})
                if path == "/v3/projects":
                    return self.send(200, {"projects": [{"id": "p-admin", "name": "admin"}]})
                return self.send(404, {"error": {"code": 404}})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path.split("?")[0] != "/v3/auth/tokens":
                    return self.send(404, {})
                pw = body["auth"]["identity"]["password"]["user"]["password"]
                if pw != ks.password:
                    ks.failed_auths += 1
                    return self.send(401, {"error": {"code": 401, "title": "Unauthorized",
                                                     "message": "The request you have made requires authentication."}})
                ks.ok_auths += 1
                ks.n += 1
                tok = f"tok-{ks.n}"
                ks.tokens.add(tok)
                now = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())
                ep = [{"id": f"e-{i}", "interface": i, "region": "RegionOne", "region_id": "RegionOne",
                       "url": ks.base + "/v3"} for i in ("internal", "public", "admin")]
                self.send(201, {"token": {
                    "methods": ["password"], "expires_at": "2999-01-01T00:00:00.000000Z", "issued_at": now,
                    "user": {"id": "u-admin", "name": "admin", "domain": {"id": "default", "name": "Default"}},
                    "project": {"id": "p-admin", "name": "admin", "domain": {"id": "default", "name": "Default"}},
                    "roles": [{"id": "r-admin", "name": "admin"}],
                    "catalog": [{"id": "s-ks", "type": "identity", "name": "keystone", "endpoints": ep}]}},
                    {"X-Subject-Token": tok})

        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def rotate(self, pw):
        self.password = pw
        self.tokens.clear()   # a password reset revokes the user's tokens


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def start_bridge(env_extra, retry="3"):
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("OS_")}
    env.update({"LISTEN_PORT": str(port), "OS_INTERFACE": "internal", "SERVICE_TYPE": "identity",
                "CREDENTIAL_RETRY_SECONDS": retry}, **env_extra)
    p = subprocess.Popen([PYTHON, SCRIPT], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            if get(port, "/_bridge/ready")[0] == 200:
                return p, port
        except Exception:
            pass
        if p.poll() is not None:
            sys.exit("bridge exited:\n" + p.stdout.read())
        time.sleep(0.1)
    p.kill()
    sys.exit("bridge did not start:\n" + p.stdout.read())


def write_secret_dir(d, ks, pw):
    """Mimic a kubelet Secret volume update: new ..data dir, atomic symlink swap, KEY -> ..data/KEY."""
    vals = {"OS_AUTH_URL": ks.base + "/v3", "OS_USERNAME": "admin", "OS_PASSWORD": pw, "OS_PROJECT_NAME": "admin",
            "OS_USER_DOMAIN_NAME": "Default", "OS_PROJECT_DOMAIN_NAME": "Default", "OS_IDENTITY_API_VERSION": "3",
            "OS_REGION_NAME": "RegionOne"}
    ts = os.path.join(d, f"..{time.time_ns()}")
    os.mkdir(ts)
    for k, v in vals.items():
        with open(os.path.join(ts, k), "w") as f:
            f.write(v)
    tmp = os.path.join(d, "..data_tmp")
    os.symlink(os.path.basename(ts), tmp)
    os.replace(tmp, os.path.join(d, "..data"))
    for k in vals:
        link = os.path.join(d, k)
        if not os.path.islink(link):
            os.symlink(os.path.join("..data", k), link)


def main():
    ks = FakeKeystone()
    work = tempfile.mkdtemp(prefix="bridge-test-")
    procs = []
    try:
        print("openrc files (CRED_DIR)")
        cred = os.path.join(work, "openrc")
        os.mkdir(cred)
        write_secret_dir(cred, ks, "p1")
        p, port = start_bridge({"CRED_DIR": cred, "OS_CLOUD": "envvars"})
        procs.append(p)
        code, body = get(port, "/projects")
        check("proxied GET /projects -> 200 with the current password", code == 200 and body.get("projects"), (code, body))
        check("/_bridge/auth -> 200 ok", get(port, "/_bridge/auth")[0] == 200)

        ks.rotate("p2")
        f0 = ks.failed_auths
        code, body = get(port, "/projects")
        check("after the rotation: 503 with an auth-bridge error (not 502, not a network failure)",
              code == 503 and "rejected the credentials" in body.get("error_message", ""), (code, body))
        check("exactly one failed authentication so far", ks.failed_auths - f0 == 1, ks.failed_auths - f0)
        for _ in range(10):
            get(port, "/projects")
        check("10 more requests within the retry period: no further authentication (no lockout hammering)",
              ks.failed_auths - f0 == 1, ks.failed_auths - f0)
        code, st = get(port, "/_bridge/auth")
        check("/_bridge/auth -> 503 state rejected, still without calling Keystone",
              code == 503 and st.get("state") == "rejected" and ks.failed_auths - f0 == 1, (code, st))
        check("/_bridge/ready stays 200 while the credentials are rejected", get(port, "/_bridge/ready")[0] == 200)
        time.sleep(3.5)
        get(port, "/projects")
        check("after the retry period: exactly one more attempt", ks.failed_auths - f0 == 2, ks.failed_auths - f0)

        o0 = ks.ok_auths
        write_secret_dir(cred, ks, "p2")
        code, body = get(port, "/projects")
        check("Secret updated -> next request rebuilds the session and succeeds, no restart",
              code == 200 and ks.ok_auths - o0 == 1, (code, body, ks.ok_auths - o0))
        check("/_bridge/auth -> 200 ok again", get(port, "/_bridge/auth")[0] == 200)
        check("the bridge process never restarted", p.poll() is None)

        print("clouds.yaml (OS_CLIENT_CONFIG_FILE), starting with a wrong password")
        clouds = os.path.join(work, "clouds.yaml")

        def write_clouds(pw):
            with open(clouds + ".tmp", "w") as f:
                f.write("clouds:\n  openstack:\n    auth:\n"
                        f"      auth_url: {ks.base}/v3\n      username: admin\n      password: {pw}\n"
                        "      project_name: admin\n      user_domain_name: Default\n      project_domain_name: Default\n"
                        "    region_name: RegionOne\n    identity_api_version: 3\n")
            os.replace(clouds + ".tmp", clouds)
        write_clouds("wrong")
        p2, port2 = start_bridge({"OS_CLIENT_CONFIG_FILE": clouds, "OS_CLOUD": "openstack"})
        procs.append(p2)
        check("starts and is ready despite rejected credentials", get(port2, "/_bridge/ready")[0] == 200)
        code, st = get(port2, "/_bridge/auth")
        check("/_bridge/auth -> 503 rejected", code == 503 and st.get("state") == "rejected", (code, st))
        write_clouds("p2")
        code, body = get(port2, "/projects")
        check("clouds.yaml fixed -> proxied request succeeds without a restart", code == 200, (code, body))
    finally:
        for p in procs:
            p.terminate()
        ks.server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    print()
    if FAILS:
        print(f"AUTH-BRIDGE TESTS FAILED: {len(FAILS)}")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("ALL AUTH-BRIDGE TESTS PASSED")


if __name__ == "__main__":
    main()
