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
