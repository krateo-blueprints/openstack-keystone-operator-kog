#!/usr/bin/env python3
"""Refuse a findby that cannot match, unless the definition declares that it must not.

WHY THIS EXISTS. rest-dynamic-controller decides whether a resource exists by listing the findby
collection and comparing each item against the CR on the declared identifiers. For each identifier
it reads the item with a map-only lookup and the CR's spec (then status) at the SAME path
(isItemMatch / isInResource). An identifier the item does not carry, or that the CR's spec does
not have, simply counts as "not a match". Nothing errors.

keystone-kog's IdentityRoleAssignment shipped that way. Its flat identifiers project_id / user_id /
role_id never matched Keystone's nested assignment items (user.id, role.id, scope.project.id). The
OAS hid that behind `additionalProperties: true`. In live data-plane run dp303, absence was
inferred on every reconcile, the grant was re-sent, and the CR never became Ready (fixed in
keystone-kog 0.4.2).

WHAT IT CHECKS, for every rendered RestDefinition that declares a findby verb:
  1. The findby's 2xx response resolves to ONE ITEM (bare array, itemsPath, or the only array), and
     that item DECLARES properties. `additionalProperties: true`, or no properties, is refused.
  2. Each identifier is MATCHABLE when it resolves in BOTH places the controller reads:
     - the item, through the normalization findby applies first: a response fieldMapping
       (inResponse -> inCustomResource) relocates a field, so a destination resolves through its
       source. A responseTransform (jq) is not evaluated, so an identifier only it supplies is
       unmatchable here; express the relocation as a fieldMapping;
     - the CR's spec, as oasgen-provider generates it: the create (else dispatch, else update)
       request body, plus every verb's parameters EXCEPT those a request-direction mapping supplies.
       Request mappings are read from BOTH `requestFieldMapping` and `fieldMapping`, because
       oasgen-provider merges the two at load (render/helper.go toDomainFieldMapping). A mapping
       whose source is `spec.<same name>` is self-referential and does not remove the field.
  3. The verb's `identifiersMatchPolicy` decides what "can match" means. It is read FROM THE VERB
     (spec.resource.verbsDescription[].identifiersMatchPolicy), and OR is the default:
       AND -> every identifier must be matchable;   OR -> at least one must be.
     A policy written at resource level is refused: it is not a field there, so it would silently
     fall back to OR.

ACTION-ONLY KINDS. For some kinds a findby that never matches is the design: the create IS the
action, and a matching findby would turn every later request into a silent no-op (the ironic KOG
measured exactly that on NodeProvision). Such a kind must DECLARE it, with a reason, as an
annotation on its RestDefinition:

    metadata:
      annotations:
        kog.openstack.krateo.io/findby-action-only: "<why matching would be wrong for this kind>"

A declared exemption is accepted only when it is coherent: the kind has a create and no get or
update verb, and its findby really cannot match. An exemption on a findby that CAN match is refused
as stale, because the create would become unreachable after the first match. An undeclared
never-matching findby is refused.

The subject is the curated OAS. The check proves "the declared item and the generated spec carry
these keys"; that the declarations are faithful to the service is what the api-ref and source
citations in each asset are for.

Exit 1 on any failure, or if no RestDefinition is rendered at all (a gate with no input must not pass).

Usage: validate-findby-identifiers.py [chart-dir]   (default: helm/openstack-keystone-operator-kog)
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

DEFAULT_CHART = "helm/openstack-keystone-operator-kog"
ACTION_ONLY = "kog.openstack.krateo.io/findby-action-only"


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


def operation(doc, verb):
    item = doc.get("paths", {}).get(verb["path"])
    if item is None:
        raise ValueError("path %s is not in the OAS" % verb["path"])
    op = item.get(verb["method"].lower())
    if op is None:
        raise ValueError("%s %s is not in the OAS" % (verb["method"], verb["path"]))
    return item, op


def response_schema(doc, verb):
    _, op = operation(doc, verb)
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


def request_mappings(verb):
    """Every request-direction mapping on a verb, from BOTH lists (oasgen merges them at load)."""
    out = list(verb.get("requestFieldMapping") or [])
    out += [m for m in (verb.get("fieldMapping") or []) if m.get("inPath") or m.get("inQuery") or m.get("inBody")]
    return out


def generated_spec(doc, verbs):
    """The CR spec oasgen-provider generates, as a schema: the base request body (create, else
    dispatch, else update) plus every verb's parameters that no request mapping supplies."""
    supplied = set()
    for v in verbs:
        for m in request_mappings(v):
            name = m.get("inPath") or m.get("inQuery")
            if not name:
                continue
            if m.get("resolver") or (m.get("inCustomResource") and m["inCustomResource"] != "spec." + name):
                supplied.add(name)
    props = {}
    by_action = {v.get("action"): v for v in verbs}
    for action in ("create", "dispatch", "update"):
        if action in by_action:
            try:
                _, op = operation(doc, by_action[action])
            except ValueError:
                break
            body = deref(doc, op.get("requestBody", {}) or {}).get("content", {}).get("application/json", {})
            if body.get("schema"):
                props.update(deref(doc, body["schema"]).get("properties", {}) or {})
            break
    for v in verbs:
        try:
            item, op = operation(doc, v)
        except ValueError:
            continue
        for p in (item.get("parameters", []) or []) + (op.get("parameters", []) or []):
            p = deref(doc, p)
            name = p.get("name", "")
            if not name or name.lower() == "authorization" or name in supplied:
                continue
            props.setdefault(name, p.get("schema", {"type": "string"}))
    return {"type": "object", "properties": props}


def check(docs):
    configmaps = {d["metadata"]["name"]: d for d in docs if d.get("kind") == "ConfigMap"}
    rds = [d for d in docs if d.get("kind") == "RestDefinition"]
    if not rds:
        return ["no RestDefinition rendered -- nothing was checked"], 0, 0
    failures, findbys = [], 0
    for rd in rds:
        name = rd["metadata"]["name"]
        res = rd["spec"]["resource"]
        verbs = res.get("verbsDescription", []) or []
        finders = [v for v in verbs if v.get("action") == "findby"]
        exemption = ((rd["metadata"].get("annotations") or {}).get(ACTION_ONLY) or "").strip()
        if "identifiersMatchPolicy" in res:
            failures.append("%s: identifiersMatchPolicy is declared at resource level, where it is not a field; it "
                            "belongs on the findby verb (verbsDescription[].identifiersMatchPolicy), and without "
                            "it the policy silently defaults to OR" % name)
        if not finders:
            if exemption:
                failures.append("%s: declares %s but has no findby verb -- remove the stale exemption" % (name, ACTION_ONLY))
            continue
        _, _, rest = rd["spec"]["oasPath"].partition("configmap://")
        _, cm_name, key = rest.split("/", 2)
        doc = yaml.safe_load(configmaps[cm_name]["data"][key])
        spec = generated_spec(doc, verbs)
        actions = {v.get("action") for v in verbs}
        for verb in finders:
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
            policy = (verb.get("identifiersMatchPolicy") or "OR").upper()
            ids = res.get("identifiers", []) or []
            matchable, why_not = [], {}
            for ident in ids:
                source = mapped.get(ident, ident)
                in_item = resolves(doc, item, source)
                in_spec = resolves(doc, spec, ident)
                if in_item and in_spec:
                    matchable.append(ident)
                    continue
                reasons = []
                if not in_item:
                    r = "not a key of the list item" + ("" if source == ident else " (via %s)" % source)
                    if verb.get("responseTransform"):
                        r += " (a responseTransform is not evaluated here; express the relocation as a fieldMapping)"
                    reasons.append(r)
                if not in_spec:
                    reasons.append("not a field of the generated CR spec (a request mapping supplies it, or no "
                                   "request body or parameter declares it)")
                why_not[ident] = "; ".join(reasons)
            can_match = bool(ids) and (len(matchable) == len(ids) if policy == "AND" else bool(matchable))
            for ident in ids:
                if ident in matchable:
                    print("ok    %s  identifier %s%s" % (where, ident,
                                                         "" if mapped.get(ident, ident) == ident else " (from %s)" % mapped[ident]))
                else:
                    print("info  %s  identifier %s unmatchable: %s" % (where, ident, why_not[ident]))
            if can_match:
                if exemption:
                    failures.append("%s: declares %s, but this findby CAN match under %s -- after the first match the "
                                    "create is unreachable; remove the exemption or the match" % (where, ACTION_ONLY, policy))
                continue
            summary = ("no identifiers declared" if not ids else
                       "%s policy, matchable: %s of %d" % (policy, matchable or "none", len(ids)))
            if exemption:
                if "create" in actions and not ({"get", "update"} & actions):
                    print("exempt %s  never matches by design (%s): %s" % (where, ACTION_ONLY, exemption))
                    continue
                failures.append("%s: declares %s, but the kind has a %s verb, so it is not action-only" %
                                (where, ACTION_ONLY, "/".join(sorted({"get", "update"} & actions))))
                continue
            failures.append("%s: findby can never match (%s), so absence is inferred every reconcile. Fix the "
                            "identifiers, or declare %s with a reason if matching would be wrong for this kind"
                            % (where, summary, ACTION_ONLY))
    return failures, len(rds), findbys


def _fixture(item, identifiers, finder_extra=None, verbs_extra=None, annotations=None, resource_extra=None,
             create_body=None):
    """A minimal rendered pair -- one ConfigMap, one RestDefinition -- for the self-test."""
    body = create_body or {"type": "object", "properties": {i.split(".")[0]: {"type": "string"} for i in identifiers}}
    oas = {"paths": {
        "/things": {
            "get": {"parameters": [{"name": "name", "in": "query", "schema": {"type": "string"}}],
                    "responses": {"200": {"content": {"application/json": {"schema": {
                        "type": "object", "properties": {"things": {"type": "array", "items": item}}}}}}}},
            "post": {"requestBody": {"content": {"application/json": {"schema": body}}},
                     "responses": {"202": {"description": "accepted"}}},
        },
        "/things/{id}": {"parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                         "get": {"responses": {"200": {"content": {"application/json": {"schema": item}}}}}},
    }}
    finder = {"action": "findby", "method": "GET", "path": "/things", "itemsPath": "things"}
    finder.update(finder_extra or {})
    verbs = [finder, {"action": "create", "method": "POST", "path": "/things"}] + (verbs_extra or [])
    resource = {"identifiers": identifiers, "verbsDescription": verbs}
    resource.update(resource_extra or {})
    meta = {"name": "rd"}
    if annotations:
        meta["annotations"] = annotations
    return [
        {"kind": "ConfigMap", "metadata": {"name": "cm"}, "data": {"oas.yaml": yaml.safe_dump(oas)}},
        {"kind": "RestDefinition", "metadata": meta,
         "spec": {"oasPath": "configmap://ns/cm/oas.yaml", "resource": resource}},
    ]


def self_test():
    """Prove each rule detects before trusting a pass. Every case is a real way a definition breaks."""
    s = {"type": "string"}
    nested = {"type": "object", "properties": {
        "user": {"type": "object", "properties": {"id": s}},
        "role": {"type": "object", "properties": {"id": s}},
        "scope": {"type": "object", "properties": {"project": {"type": "object", "properties": {"id": s}}}}}}
    flat_ids = ["project_id", "user_id", "role_id"]
    mapping = [{"inResponse": "scope.project.id", "inCustomResource": "status.project_id"},
               {"inResponse": "user.id", "inCustomResource": "status.user_id"},
               {"inResponse": "role.id", "inCustomResource": "status.role_id"}]
    named = {"type": "object", "properties": {"name": s, "id": s}}
    get_verb = [{"action": "get", "method": "GET", "path": "/things/{id}"}]
    query_only_body = {"type": "object", "properties": {"other": s}}
    reason = {ACTION_ONLY: "the create is the action; matching would make later requests silent no-ops"}
    cases = [
        ("nested item, flat identifiers (dp303)", _fixture(nested, flat_ids, {"identifiersMatchPolicy": "AND"}), True),
        ("nested item, mapped identifiers", _fixture(nested, flat_ids, {"identifiersMatchPolicy": "AND",
                                                                        "fieldMapping": mapping}), False),
        ("undeclared item", _fixture({"type": "object", "additionalProperties": True}, flat_ids), True),
        # Policy is per verb, OR by default.
        ("OR (default): one of two identifiers matchable", _fixture(named, ["name", "bogus"]), False),
        ("AND: one of two identifiers matchable", _fixture(named, ["name", "bogus"],
                                                           {"identifiersMatchPolicy": "AND"}), True),
        ("policy declared at resource level", _fixture(named, ["name"], resource_extra={
            "identifiersMatchPolicy": "AND"}), True),
        # Request mappings from BOTH lists remove the parameter from the generated spec.
        ("query param in spec (no mapping): matchable", _fixture(named, ["name"], create_body=query_only_body), False),
        ("query param supplied by requestFieldMapping: not in spec", _fixture(named, ["name"], {
            "requestFieldMapping": [{"inQuery": "name", "inCustomResource": "spec.other"}]},
            create_body=query_only_body), True),
        ("query param supplied by fieldMapping: not in spec", _fixture(named, ["name"], {
            "fieldMapping": [{"inQuery": "name", "inCustomResource": "spec.other"}]},
            create_body=query_only_body), True),
        ("self-referential mapping keeps the spec field", _fixture(named, ["name"], {
            "fieldMapping": [{"inQuery": "name", "inCustomResource": "spec.name"}]},
            create_body=query_only_body), False),
        # Action-only: declared, coherent exemptions pass; undeclared, stale or incoherent ones fail.
        ("never matches, undeclared", _fixture(named, ["node_id"]), True),
        ("never matches, declared action-only", _fixture(named, ["node_id"], annotations=reason), False),
        ("declared action-only but the kind has a get", _fixture(named, ["node_id"], verbs_extra=get_verb,
                                                                 annotations=reason), True),
        ("declared action-only but the findby matches", _fixture(named, ["name"], annotations=reason), True),
        ("declared action-only with an empty reason", _fixture(named, ["node_id"], annotations={ACTION_ONLY: " "}), True),
    ]
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
