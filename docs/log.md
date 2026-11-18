---
type: Log
title: openstack-keystone-operator-kog — log
description: Curated chronological history of the openstack-keystone-operator-kog blueprint — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, log, history]
timestamp: 2026-11-18T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.


## 2026-11-18 — findby gate: reachability (an unreachable findby, a create that may not run)

rest-dynamic-controller fills a call's path parameters from spec fields by name before it applies any
request mapping (0.80.0 `builder.go` `BuildCallConfig`: spec at L179, mappings at L192-193). So a get
whose path parameters all come from required spec fields is used from the first reconcile. The ironic
KOG pinned this behaviour at oasgen 0.59.0 and later. Two new checks in
`hack/validate-findby-identifiers.py` follow from it:
- **A findby on such a kind is refused as unreachable.** It is reported as a reachability problem,
  not an identifier problem.
- **Its create runs only when that get reports absence.** The gate prints every such kind. It is fine
  when the get declares a discriminator, a `notFoundBody` or a 404 response; otherwise it prints a
  WARNING, not a failure. The create's path does not settle it: nova's quota GET answers 200 for any
  project.

The Keystone federation GETs (identity provider, mapping, protocol) now declare the 404 Keystone
returns when the object is absent (`exception.*NotFound`). All five keystone kinds that meet the
precondition print "fine". Also removed: two `hack/__pycache__/*.pyc` files committed by mistake (one
in #25), and `__pycache__/` is now ignored.

## 2026-11-18 — findby gate: per-verb policy, both mapping lists, declared action-only kinds

`hack/validate-findby-identifiers.py` now models three things it ignored. All three came from the
ironic KOG, whose gate had already met each one:
- `identifiersMatchPolicy` is read from the findby verb, and OR is the default. Under OR one matchable
  identifier is enough; under AND every identifier must be matchable. A policy written at resource
  level is refused, because it would silently fall back to OR.
- An identifier must also exist in the CR spec oasgen-provider generates (the request body plus the
  parameters no request mapping supplies). Request mappings are read from both `requestFieldMapping`
  and `fieldMapping`, which oasgen-provider merges at load.
- A kind whose findby must never match (the create is the action) can declare that with the
  annotation `kog.openstack.krateo.io/findby-action-only: <reason>`. The exemption is accepted only on
  a create-only kind whose findby really cannot match. An undeclared never-matching findby, or a stale
  exemption, is refused.

The self-test grew from 3 to 15 detector cases.

## 2026-11-18 — 0.4.2: IdentityRoleAssignment becomes Ready

Measured on live data-plane run dp303 (GKE, blueprint 0.3.73, keystone-kog 0.4.1,
rest-dynamic-controller 0.80.0): an `IdentityRoleAssignment` stayed Ready=False while Synced=True.
The controller logged `PUT …/roles/{r}` → 204, then `GET /role_assignments` with absence inferred
again for the same generation, and sent the PUT again, forever.

The kind was observed with `findby GET /role_assignments` on the identifiers `project_id`, `user_id`,
`role_id`. Keystone lists each assignment nested, as `user.id`, `role.id` and `scope.project.id`
(`keystone/api/role_assignments.py` `_format_entity`), so those keys were never present and the match
could never succeed. The OAS item schema was `additionalProperties: true`, so nothing showed it.

It now uses Keystone's check endpoint, `GET /projects/{project_id}/users/{user_id}/roles/{role_id}`
(204 granted, 404 not), like `IdentityGroupRoleAssignment`. The identifiers are unchanged because
they are immutable on an installed RestDefinition, and with no findby they are compared against
nothing. A new CI gate, `hack/validate-findby-identifiers.py`, refuses any findby whose identifiers
are not keys of its declared list item, and any findby item that declares no properties.

## 2026-11-13 — 0.4.1: the auth-bridge survives a password rotation

Measured by the OpenStack blueprint on GKE: after its upgrade rotated the Keystone admin password, the
auth-bridge kept the password it read at start (`envFrom`) and called Keystone with it every ~10 s
(316 failed `POST /v3/auth/tokens`), which locked the admin account for every client for 30 minutes.
Its readiness probe proxied `GET /` to Keystone, so the 401 made the pod unready, the Service lost its
endpoints, and every controller saw "connection refused" instead of an identity error.

The credentials Secret (openrc or clouds.yaml) is now mounted and re-read: a changed Secret rebuilds
the session with no restart. Rejected credentials get one attempt, then 503 with the reason and no
call to Keystone until they change or `authBridge.credentialRetrySeconds` (default 300) passes.
Readiness is `/_bridge/ready`, served by the proxy itself; `/_bridge/auth` reports the auth state.
The Deployment rolls when the proxy script changes (`checksum/script`). Gated in CI by
`hack/test-auth-bridge.py`: the real script in front of a fake Keystone (14 assertions). The same
scenario against the 0.4.0 script sent 11 failed authentications for 11 requests and answered 502.

## 2026-11-12 — 0.4.0: domains by name for identity providers and projects

`IdentityFederationProvider` accepts `spec.identity_provider.domain` and `IdentityProject` accepts
`spec.project.domain`: a domain NAME, resolved to its id at create by a lookup (`GET /domains?name=`),
the way `IdentityGroup` already resolves its domain. A domain created by an `IdentityDomain` gets a
server-generated id, so before this its id had to be copied into these resources by hand. An explicit
`domain_id` still wins and skips the lookup; `domain` is never sent to Keystone. Both are additive: existing
CRs are unchanged. The two RestDefinitions also move from the deprecated `requestFieldMapping` to
`fieldMapping` (same behaviour).

Measured on GKE (Keystone 2026.1 from the OpenStack blueprint 0.3.47, oasgen-provider 0.60.0): an
`IdentityFederationProvider` with `domain: keycloak` was created with the `keycloak` domain's id as its
`domain_id`, and `IdentityProject`s with `domain: keycloak` were created in that domain (rendered by
krateo-openstack-federation).

## 2026-11-12 — 0.3.2: appVersion corrected to 2026.1

No chart change. 0.3.1 set `appVersion` to `2025.1`, which is wrong: the validation ran the OpenStack
blueprint 0.3.47's default `keystone_api` image, `quay.io/airshipit/keystone:2026.1-ubuntu_noble`.
`2025.1` is the tag of the separate OIDC-enabled image (`keystone-oidc`), which that run did not use.

## 2026-11-12 — 0.3.1: listed on the Marketplace

No chart change. The repo now uses the org's canonical release workflow: a tag is refused unless
the tagged commit passed `lint.yaml` (which now also runs on every push to `main`), and the chart
goes to the Marketplace blueprints index as well as GHCR, with the stamped CompositionDefinition
inside the archive. 0.3.0 was published to GHCR only. `appVersion` is now the Keystone release the
chart is validated against (`2025.1`); it had been left at `0.2.0`. See [release](release.md).

## 2026-11-12 — 0.3.0: groups and group role assignments; credentials from the blueprint

`IdentityGroup` is on by default, modelled flat with the envelope handled by request/response
transforms (the envelope property had broken crdgen), its domain addressed by name.
`IdentityGroupRoleAssignment` is new and on by default: a role granted to a group on a project, by
names. Both need oasgen-provider >= 0.58.0. `authBridge.openrcSecret` lets the auth proxy use the
OpenStack blueprint's own admin Secret. Validated end to end against a real Keystone on GKE (see
[api](api.md)).

The schema no longer `required`s `authBridge` or `authBridge.upstreamEndpoint`. Both have
defaults (an empty endpoint means auto-discovery), and core-provider makes a `required` key
mandatory on the Composition CR before those defaults apply, so a Composition that omitted them
was rejected. CI now gates this with `hack/check-schema-required.py`.

## 0.2.0

- OS-FEDERATION resources added: `IdentityFederationProvider`, `IdentityMapping`,
  `IdentityFederationProtocol`. Federation trust (external OIDC IdP → Keystone → Horizon)
  is now declared as CRs and was validated live end-to-end (GitHub → Keycloak → Keystone).
- Federation gotchas encoded in `chart/samples/federation.yaml`: `update` maps to `PATCH`
  (Keystone `PUT` is create-only, 409 on existing); no `domain` in the mapping's `projects`
  local rule; pin the IdP `domain_id`; clean up stale shadow users on IdP recreate.

## 0.1.0 (initial)

- KOG packaging of Keystone identity v3: `IdentityProject`, `IdentityUser`, `IdentityRole`,
  `IdentityDomain`, `IdentityRoleAssignment` validated end-to-end (real objects created,
  role grant `PUT → 204`).
- Auth-bridge introduced: an openstacksdk reverse proxy that injects a fresh `X-Auth-Token`
  on every call (auto-refreshing, in-cluster), so the plain-HTTP controller can reach
  Keystone without token exchange.
- `Identity*` Kind prefix adopted to avoid the crdgen Kind-vs-envelope-property collision.
- `IdentityGroup` shipped disabled — crdgen emits an undefined Go type `Group` for the
  `group` envelope property (`unknown type Group`); pending an upstream crdgen fix.
- `IdentityApplicationCredential` shipped disabled — create leaks the path-only `user_id`
  into the body (Keystone 400); `get`/`delete` work. Needs a KOG exclude-from-body mapping.
