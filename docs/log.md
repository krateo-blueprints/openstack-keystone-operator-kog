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
