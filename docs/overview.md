---
type: Architecture
title: openstack-keystone-operator-kog — overview
description: What the blueprint is and how it is built — the KOG pipeline (OAS subset → RestDefinition → generated CRD), the Identity* Kind naming, the auth-refreshing proxy, and the OS-FEDERATION resource set.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, oasgen-provider, rest-dynamic-controller, architecture]
timestamp: 2026-08-11T00:00:00Z
---

# Overview

`openstack-keystone-operator-kog` is a **Krateo Operator Generator (KOG)** blueprint. It
does not ship a compiled controller. Instead it ships, per Keystone resource, a
hand-curated OpenAPI 3.0 subset and a `RestDefinition` that tells Krateo how to drive that
API. Krateo's `oasgen-provider` reads the `RestDefinition`, generates a CRD for the
resource, and the generic `rest-dynamic-controller` reconciles each custom resource into a
real Keystone object over HTTP.

## The KOG pipeline

```
chart/assets/<res>.yaml        (Keystone v3 OAS subset)
        │  bundled into a ConfigMap by templates/configmap-<res>.yaml
        ▼
templates/rd-<res>.yaml        (RestDefinition: oasPath + resource verbs)
        │  read by oasgen-provider
        ▼
Identity<Res> CRD              (generated) + Identity<Res>Configuration CRD
        │  reconciled by rest-dynamic-controller
        ▼
Keystone object                (HTTP call through the auth-bridge)
```

The `RestDefinition` names the resource `kind`, its `identifiers`, any
`additionalStatusFields`, and one entry per verb (`create` / `get` / `update` / `delete`,
or `findby` / `create` / `delete` for actions) with the HTTP method, path, and the
mapping between path params and CR fields. Each verb's request/response shape comes from
the OAS subset in `chart/assets/`.

## Why every Kind is `Identity*`

Every Keystone payload is envelope-wrapped — `{project:{…}}`, `{user:{…}}`,
`{role:{…}}`, `{domain:{…}}` — so the CR spec is `spec.project.*`, `spec.user.*`, and so
on. crdgen would collide the Kind name with that envelope property, so every Kind is
prefixed `Identity*` (`IdentityProject`, `IdentityUser`, …), the same reason Nova's
`Server` becomes `Instance`. Unlike Nova/Ironic, Keystone updates are a plain `PATCH`
(not JSON-Patch), so CRUD resources carry an `update` verb.

## The resource set

| Kind | Keystone API | Verbs | Default |
|------|--------------|-------|---------|
| `IdentityProject` | `/v3/projects` | create / get / update / delete | on |
| `IdentityUser` | `/v3/users` | create / get / update / delete | on |
| `IdentityRole` | `/v3/roles` | create / get / update / delete | on |
| `IdentityDomain` | `/v3/domains` | create / get / update / delete | on |
| `IdentityRoleAssignment` | `PUT/DELETE /v3/projects/{p}/users/{u}/roles/{r}` | findby / grant / revoke | on |
| `IdentityGroup` | `/v3/groups` | create / get / update / delete | off — crdgen quirk |
| `IdentityApplicationCredential` | `/v3/users/{u}/application_credentials` | create / get / delete | off — body-leak |
| `IdentityFederationProvider` | `/v3/OS-FEDERATION/identity_providers/{id}` | create / get / update / delete | on |
| `IdentityMapping` | `/v3/OS-FEDERATION/mappings/{id}` | create / get / update / delete | on |
| `IdentityFederationProtocol` | `/v3/OS-FEDERATION/identity_providers/{idp}/protocols/{id}` | create / get / update / delete | on |

`IdentityRoleAssignment` is an idempotent grant (a `PUT`/`DELETE` on a composite path,
not a CRUD object) modeled as a single CR; re-firing the `PUT` is a harmless no-op.
`IdentityDomain` must be disabled (`update` with `enabled:false`) before it can be
deleted. Two resources ship **disabled** with documented limitations — see
[configuration.md](configuration.md#disabled-by-default-resources).

## Federation (OS-FEDERATION)

The three `IdentityFederation*` / `IdentityMapping` kinds make Keystone's OIDC/SAML
federation trust GitOps-native: declare an external IdP, a claims→identity mapping, and
the protocol binding as CRs instead of hand-running `openstack federation …`. Unlike
projects/users (`POST` → server-assigned UUID), a federation object is addressed by a
**client-chosen id** in the path (`PUT`), so `id` is a user-set natural-key spec field —
no `findby` needed. Keystone-specific gotchas the samples encode are documented in
[usage.md](usage.md#federation-os-federation) and
[quickstart.md](quickstart.md).

## Auth: the auto-refreshing openstacksdk proxy

The `rest-dynamic-controller` speaks plain HTTP and cannot perform Keystone token
exchange. The chart ships an **auth-bridge**: a small stateless reverse proxy
(`chart/scripts/openstack-auth-proxy.py`, run in the `openstack-client` image) that
authenticates with an admin `clouds.yaml`, discovers the `identity` endpoint, and injects
a **fresh** `X-Auth-Token` on every call (keystoneauth refreshes it automatically). Unlike
a static-token nginx rewrite it never expires and works in-cluster (no public-DNS resolver
trap). Each OAS subset's `servers[0].url` points the generated controllers at the bridge.

You supply the admin `clouds.yaml` in a Secret named by `authBridge.cloudsSecret`
(default `keystone-clouds`). See [configuration.md](configuration.md#auth-bridge) for the
full auth-bridge surface.
