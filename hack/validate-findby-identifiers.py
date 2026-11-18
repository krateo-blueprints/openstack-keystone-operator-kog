#!/usr/bin/env python3
"""Refuse a findby whose identifiers are not keys of the list item it searches.

WHY THIS EXISTS. rest-dynamic-controller decides whether a resource exists by listing the findby
collection and comparing each item against the CR on the declared identifiers. It reads each
identifier out of the item with a map-only lookup (unstructured.NestedFieldNoCopy, in isItemMatch).
An identifier the item does not carry is simply "not a match". So when the identifiers name keys
the item never has, findby can never match, absence is inferred on every reconcile, and create
fires again, forever. Nothing errors.

IdentityRoleAssignment shipped that way. Its identifiers were project_id / user_id / role_id, and
Keystone lists each assignment NESTED: user.id, role.id, scope.project.id
(keystone/api/role_assignments.py _format_entity). The OAS hid it by declaring the item
`additionalProperties: true` with no properties, so no tool could see what the item carried. Live
data-plane run dp303 (2026-11-18) sat Ready=False forever while the grant was re-sent every
reconcile.

WHAT IT CHECKS, for every rendered RestDefinition that declares a findby verb:
  1. The findby's 2xx response resolves to ONE ITEM: the bare array's items, the array at
     itemsPath, or the only array property.
  2. That item DECLARES its shape: an object with `properties`. An item that is
     `additionalProperties: true`, or that has no properties, is refused. A schema that admits
     anything says nothing about what the identifiers will find.
  3. Every identifier resolves in the item, through the same normalization findby applies before
     matching:
     - A response-direction fieldMapping on the findby (inResponse -> inCustomResource) relocates a
       field, so an identifier that is a mapping destination is resolved through its SOURCE path.
     - A responseTransform (jq) can't be read statically, so a findby that declares one is refused
       unless every identifier still resolves in the untransformed item.

The subject is the curated OAS. The check proves "the declared item carries these keys"; that the
declaration is faithful to the service is what the api-ref and source citations in each asset are
for.

Exit 1 on any failure, or if no RestDefinition is rendered at all (a gate with no input must not pass).

Usage: validate-findby-identifiers.py [chart-dir]   (default: helm/openstack-keystone-operator-kog)
"""
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

DEFAULT_CHART = "helm/openstack-keystone-operator-kog"


def render(chart):
    """Render a copy of the chart with the CHART_VERSION placeholder stamped (helm rejects it as a
    version), so the check runs the same locally and in CI without touching the working tree."""
    tmp = tempfile.mkdtemp()
    try:
        dst = os.path.join(tmp, "chart")
        shutil.copytree(chart, dst)
        cy = os.path.join(dst, "Chart.yaml")
        with open(cy) as f:
            text = f.read().replace("CHART_VERSION", "0.0.0-ci")
        with open(cy, "w") as f:
            f.write(text)
        proc = subprocess.run(["helm", "template", "release", dst, "--namespace", "krateo-system"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit("FAIL: helm template %s failed -- nothing was checked" % chart)
        return [d for d in yaml.safe_load_all(proc.stdout) if d]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def deref(doc, node, depth=0):
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/") or depth > 32:
            raise ValueError("unsupported $ref %r" % ref)
        cur = doc
        for seg in ref[2:].split("/"):
            cur = cur[seg]
        node, depth = cur, depth + 1
    return node


def response_schema(doc, verb):
    item = doc.get("paths", {}).get(verb["path"])
    if item is None:
        raise ValueError("path %s is not in the OAS" % verb["path"])
    op = item.get(verb["method"].lower())
    if op is None:
        raise ValueError("%s %s is not in the OAS" % (verb["method"], verb["path"]))
    for code, resp in sorted(op.get("responses", {}).items()):
        if str(code).startswith("2"):
            content = deref(doc, resp).get("content", {}).get("application/json")
            if content and "schema" in content:
                return deref(doc, content["schema"])
    raise ValueError("%s %s declares no 2xx application/json schema" % (verb["method"], verb["path"]))


def list_item(doc, schema, items_path):
    if schema.get("type") == "array":
        return deref(doc, schema.get("items", {}))
    props = schema.get("properties", {}) or {}
    if items_path:
        cur = schema
        for seg in items_path.lstrip(".").split("."):
            cur = deref(doc, (cur.get("properties", {}) or {}).get(seg, {}))
        if cur.get("type") != "array":
            raise ValueError("itemsPath %r does not resolve to an array" % items_path)
        return deref(doc, cur.get("items", {}))
    arrays = [k for k, v in props.items() if deref(doc, v).get("type") == "array"]
    if len(arrays) == 1:
        return deref(doc, deref(doc, props[arrays[0]]).get("items", {}))
    if not arrays:
        return schema  # the controller treats a non-list body as a list of one
    raise ValueError("findby response has several arrays %s and no itemsPath" % arrays)


def resolves(doc, schema, dotted):
    cur = deref(doc, schema)
    for seg in dotted.split("."):
        props = cur.get("properties", {}) or {}
        if seg not in props:
            return False
        cur = deref(doc, props[seg])
    return True


def check(docs):
    configmaps = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ConfigMap"}
    rds = [d for d in docs if d.get("kind") == "RestDefinition"]
    if not rds:
        return ["no RestDefinition rendered -- nothing was checked"], 0, 0
    failures, findbys = [], 0
    for rd in rds:
        name = rd["metadata"]["name"]
        res = rd["spec"]["resource"]
        verbs = [v for v in res.get("verbsDescription", []) if v.get("action") == "findby"]
        if not verbs:
            continue
        _, _, rest = rd["spec"]["oasPath"].partition("configmap://")
        _, cm_name, key = rest.split("/", 2)
        doc = yaml.safe_load(configmaps[cm_name]["data"][key])
        for verb in verbs:
            findbys += 1
            where = "%s findby %s %s" % (name, verb["method"], verb["path"])
            try:
                item = list_item(doc, response_schema(doc, verb), verb.get("itemsPath", ""))
            except (ValueError, KeyError) as e:
                failures.append("%s: cannot resolve the list item schema: %s" % (where, e))
                continue
            if not (item.get("properties") or {}):
                failures.append(
                    "%s: the list item declares no properties%s, so nothing says what the identifiers "
                    "will find. Declare the item's real shape (cite the service's list formatter)."
                    % (where, " (additionalProperties: true)" if item.get("additionalProperties") is True else ""))
                continue
            mapped = {}
            for m in verb.get("fieldMapping", []) or []:
                if m.get("inResponse") and m.get("inCustomResource"):
                    dest = m["inCustomResource"]
                    for prefix in ("status.", "spec."):
                        if dest.startswith(prefix):
                            dest = dest[len(prefix):]
                    mapped.setdefault(dest, m["inResponse"])
            ids = res.get("identifiers", []) or []
            if not ids:
                failures.append("%s: findby declares no identifiers, so it can never match" % where)
            for ident in ids:
                source = mapped.get(ident, ident)
                if resolves(doc, item, source):
                    print("ok    %s  identifier %s%s" % (where, ident,
                                                         "" if source == ident else " (from %s)" % source))
                    continue
                why = "is not a key of the list item"
                if verb.get("responseTransform"):
                    why += " (this findby has a responseTransform, which cannot be checked statically; " \
                           "express the relocation as a response fieldMapping instead)"
                failures.append("%s: identifier %r%s %s, so findby can never match and create re-fires "
                                "every reconcile" % (where, ident,
                                                     "" if source == ident else " (via %s)" % source, why))
    return failures, len(rds), findbys


def _fixture(item, identifiers, field_mapping=None):
    """A minimal rendered pair -- one ConfigMap, one RestDefinition -- for the self-test."""
    oas = {"paths": {"/things": {"get": {"responses": {"200": {"content": {"application/json": {
        "schema": {"type": "object", "properties": {"things": {"type": "array", "items": item}}}}}}}}}}}
    verb = {"action": "findby", "method": "GET", "path": "/things", "itemsPath": "things"}
    if field_mapping:
        verb["fieldMapping"] = field_mapping
    return [
        {"kind": "ConfigMap", "metadata": {"name": "cm"}, "data": {"oas.yaml": yaml.safe_dump(oas)}},
        {"kind": "RestDefinition", "metadata": {"name": "rd"},
         "spec": {"oasPath": "configmap://ns/cm/oas.yaml",
                  "resource": {"identifiers": identifiers, "verbsDescription": [verb]}}},
    ]


def self_test():
    """Prove the detector detects before trusting a pass: Keystone's real nested assignment shape
    with flat identifiers must fail, the same shape with response fieldMappings must pass, and an
    undeclared (additionalProperties: true) item must fail."""
    nested = {"type": "object", "properties": {
        "user": {"type": "object", "properties": {"id": {"type": "string"}}},
        "role": {"type": "object", "properties": {"id": {"type": "string"}}},
        "scope": {"type": "object", "properties": {"project": {"type": "object", "properties": {
            "id": {"type": "string"}}}}}}}
    flat_ids = ["project_id", "user_id", "role_id"]
    mapping = [{"inResponse": "scope.project.id", "inCustomResource": "status.project_id"},
               {"inResponse": "user.id", "inCustomResource": "status.user_id"},
               {"inResponse": "role.id", "inCustomResource": "status.role_id"}]
    cases = [
        ("nested item, flat identifiers", _fixture(nested, flat_ids), True),
        ("nested item, mapped identifiers", _fixture(nested, flat_ids, mapping), False),
        ("undeclared item", _fixture({"type": "object", "additionalProperties": True}, flat_ids), True),
    ]
    import contextlib
    import io
    for label, docs, want_fail in cases:
        with contextlib.redirect_stdout(io.StringIO()):
            failures, _, _ = check(docs)
        if bool(failures) != want_fail:
            raise SystemExit("FAIL: self-test %r: expected %s, got %s -- the detector is broken, so a pass "
                             "would mean nothing" % (label, "a failure" if want_fail else "a pass",
                                                     failures or "a pass"))
    print("self-test: %d detector cases behave" % len(cases))


def main():
    self_test()
    chart = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CHART
    failures, n_rd, n_findby = check(render(chart))
    print("checked %d RestDefinitions, %d findby verb(s)" % (n_rd, n_findby))
    for f in failures:
        print("FAIL: " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
