---
type: Usage
title: openstack-keystone-operator-kog — usage
description: How to install the operator (Helm or as a Krateo Composition), supply the clouds.yaml Secret, apply the first Identity* resource, and drive Keystone OS-FEDERATION as CRs.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, install, composition, federation]
timestamp: 2026-08-11T00:00:00Z
---

# Usage

Two ways to install: as a plain Helm chart (fastest for a local try), or as a Krateo
Composition through the `CompositionDefinition` this repo registers. Either way you first
need the KOG provider and a `clouds.yaml` Secret.

## Prerequisites

Krateo's KOG provider in the cluster:

```bash
helm repo add krateo https://charts.krateo.io && helm repo update
helm upgrade --install oasgen-provider krateo/oasgen-provider -n krateo-system --create-namespace
```

An admin `clouds.yaml` for your Keystone, stored in a Secret named by
`authBridge.cloudsSecret` (default `keystone-clouds`, key `clouds.yaml`):

```bash
kubectl -n krateo-system create secret generic keystone-clouds --from-file=clouds.yaml=clouds.yaml
```

```yaml
# clouds.yaml
clouds:
  openstack:
    auth:
      auth_url: http://keystone-api.openstack.svc.cluster.local:5000/v3
      username: admin
      password: password
      project_name: admin
      user_domain_name: Default
      project_domain_name: Default
    region_name: RegionOne
    identity_api_version: 3
    interface: internal
```

## Install — as a Helm chart

```bash
helm upgrade --install keystone-kog ./chart -n krateo-system \
  --set authBridge.upstreamEndpoint=http://keystone-api.openstack.svc.cluster.local:5000/v3
kubectl -n krateo-system wait restdefinition/keystone-kog-project --for=condition=Ready --timeout=300s
```

This deploys the auth-bridge and the enabled per-resource `RestDefinition`s. Krateo then
generates the `Identity*` CRDs.

## Install — as a Krateo Composition

The chart is registered by [`compositiondefinition.yaml`](../compositiondefinition.yaml)
and published to `oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog`.
Apply the `CompositionDefinition`, then create the Composition CR (see
[examples/composition](../examples/composition/README.md)):

```bash
kubectl apply -f compositiondefinition.yaml
kubectl apply -f examples/composition.yaml
```

The Composition CR carries the same values surface (`authBridge`, `restdefinitions`) as
the chart — see [configuration.md](configuration.md).

## Apply your first resource

Each `Identity*` Kind pairs with a generated `<Kind>Configuration` that carries the bearer
token (from the OAS `http`/`bearer` security scheme). Because the auth-bridge injects the
real `X-Auth-Token`, that token is a placeholder — any non-empty Secret value works:

```bash
kubectl -n krateo-system create secret generic keystone-token --from-literal=token=managed-by-proxy
kubectl -n krateo-system apply -f chart/samples/identity-resources.yaml
kubectl -n krateo-system get identityprojects.identity.openstack.krateo.io -w
```

The created project appears in Horizon under **Identity → Projects**. Apply
`IdentityUser`, `IdentityRole`, and `IdentityRoleAssignment` the same way; see
[quickstart.md](quickstart.md) for the full walk-through with a screenshot.

## Federation (OS-FEDERATION)

`chart/samples/federation.yaml` declares a Keystone federation trust — an external OIDC
IdP, a claims→identity mapping, and the protocol binding — entirely as CRs. Validated
live end-to-end (GitHub → Keycloak → Keystone → Horizon). Four Keystone-specific gotchas
the samples encode:

- **Update is `PATCH`, not `PUT`.** Keystone's `PUT /OS-FEDERATION/.../{id}` is create-only
  and returns **409** if the object exists; the `update` verb maps to `PATCH`.
- **No `domain` in the mapping's `projects` local rule** — Keystone rejects it; the
  project domain is inferred from the `user` rule.
- **Pin the IdP's `domain_id`** to your managed domain, or Keystone auto-creates a per-IdP
  domain and auto-provisioned projects land there, orphaned. Pinning it makes
  auto-provisioning **reuse** the managed project (matched by name in that domain).
- Recreating an IdP with the same id needs stale **shadow-user cleanup** in the federation
  domain (otherwise re-login hits `409 store federated_user - Duplicate`).

```bash
kubectl -n krateo-system apply -f chart/samples/federation.yaml
```

## Notes

- **`IdentityDomain`** must be disabled (`update` with `enabled:false`) before it can be
  deleted.
- **`IdentityGroup`** and **`IdentityApplicationCredential`** ship disabled by default —
  see [configuration.md](configuration.md#disabled-by-default-resources).
- An `IdentityApplicationCredential` is the production answer to the expiring-token problem
  the other KOG operators (nova/ironic) hit: mint one here, then point their
  proxies/`clouds.yaml` at it.
