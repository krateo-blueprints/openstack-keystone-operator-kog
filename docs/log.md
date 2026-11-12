---
type: Log
title: openstack-keystone-operator-kog — log
description: Curated chronological history of the openstack-keystone-operator-kog blueprint — notable changes and decisions, not a generated changelog.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, log, history]
timestamp: 2026-08-11T00:00:00Z
---

# Log

Curated history; release notes live in GitHub Releases.


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
