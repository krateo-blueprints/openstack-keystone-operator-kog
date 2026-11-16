#!/usr/bin/env python3
"""No document tells a reader to authenticate to Keystone with an OpenStack-Helm published password.

WHY: from krateo-openstack-blueprint 0.3.68 the Keystone admin password (and every service user's) is generated
per install. docs/usage.md and docs/quickstart.md still built clouds.yaml with `password: password` (fixed in #22,
2026-11-16): an instruction that fails with a 401 on every such install and republishes the removed default.

WHAT: every repo-authored Markdown file fails when it passes a PUBLISHED value as a credential:
  - password: / os_password: <value>            (a clouds.yaml / YAML auth block)
  - OS_PASSWORD=<value>                         (an openrc or `kubectl run --env`)
  - --password <value> / --os-password <value>  (a CLI argument)
  - as `<user>` / `<value>`                     (a login instruction)
A key-name mention such as `username`/`password` is not a credential and is not matched. Placeholders
(`<...>`) never match. No document found is a failure: an empty scan is not a pass.

PUBLISHED is pinned, since this repo carries no OpenStack-Helm chart to read it from. Source: every non-empty
endpoints.identity.auth.<user>.password in krateo-openstack-blueprint blueprints/*/chart/values.yaml at 3f695c6
(99 entries, one distinct value). That repo's own gate, hack/validate-docs-no-published-credentials.py, reads
them live; update this list if it ever reports a second value.
"""
import os
import re
import subprocess
import sys

PUBLISHED = {"password"}

ROOT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
files = subprocess.run(["git", "-C", ROOT, "ls-files", "*.md"], capture_output=True, text=True, check=True).stdout.split()
if not files:
    print("FAILED MEASUREMENT: no Markdown document found under %s; nothing was checked" % ROOT)
    sys.exit(2)

PATTERNS = [
    re.compile(r"""^\s*(?:-\s*)?(?:os_)?password:\s*['"]?([^\s'"#]+)"""),
    re.compile(r"""\bOS_PASSWORD=['"]?([^\s'"\\]+)"""),
    re.compile(r"""--(?:os-)?password[= ]['"]?([^\s'"\\]+)"""),
    re.compile(r"""\bas `[^`]+` */ *`([^`]+)`"""),
]
failures = []
for f in files:
    for n, line in enumerate(open(os.path.join(ROOT, f), errors="replace"), 1):
        for rx in PATTERNS:
            for m in rx.finditer(line):
                if m.group(1) in PUBLISHED:
                    failures.append("%s:%d passes a published OpenStack-Helm password as a credential: %s"
                                    % (f, n, line.strip()[:120]))
for x in failures:
    print("::error::" + x)
if failures:
    print("There is no default to document: point the auth-bridge at the blueprint's Secret "
          "(authBridge.openrcSecret: keystone-keystone-admin) or use a placeholder.")
    sys.exit(1)
print("OK: %d document(s) pass no published OpenStack-Helm password (%d pinned value(s))" % (len(files), len(PUBLISHED)))
