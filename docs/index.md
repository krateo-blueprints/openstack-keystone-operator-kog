---
type: Component
title: openstack-keystone-operator-kog — index
description: The map of the openstack-keystone-operator-kog doc bundle — a Krateo Operator Generator (KOG) blueprint that turns OpenStack Keystone (identity v3) resources into native Kubernetes custom resources.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, openstack, keystone, identity, blueprint]
timestamp: 2026-08-11T00:00:00Z
---

# openstack-keystone-operator-kog

A Krateo Operator Generator (KOG) blueprint that packages **OpenStack Keystone
(identity v3)** as native Kubernetes custom resources. There is no hand-written
controller: a hand-curated OpenAPI subset per resource plus Krateo's generic
`oasgen-provider` and `rest-dynamic-controller` reconcile each `Identity*` CR into a
real Keystone object.

`kubectl apply` an `IdentityProject` / `IdentityUser` / `IdentityRole` / … and the
generated controller calls Keystone through a bundled **auth-bridge** proxy that keeps
a fresh `X-Auth-Token` on every request.

## Doc map

- [overview.md](overview.md) — what the blueprint is and how it is built: the KOG
  pipeline, the `Identity*` Kind naming, the auth-bridge, and the OS-FEDERATION set.
- [usage.md](usage.md) — install the operator (Helm or as a Krateo Composition), supply
  the `clouds.yaml` Secret, and apply your first `IdentityProject`.
- [configuration.md](configuration.md) — the whole `values.yaml` surface: per-resource
  toggles and the auth-bridge config, typed by `values.schema.json`.
- [api.md](api.md) — the `CompositionDefinition` CRD this blueprint registers, and the
  `RestDefinition` / `Identity*` CRDs the chart emits.
- [examples.md](examples.md) — the runnable examples index.
- [release.md](release.md) — how a release ships the chart to GHCR.
- [log.md](log.md) — curated history.
- [quickstart.md](quickstart.md) — install and see a resource appear in Horizon.

## Repo layout

```
chart/
  Chart.yaml
  values.yaml                 # per-resource toggles + auth-bridge config
  values.schema.json          # typed values surface
  assets/                     # one Keystone OAS subset per resource
  scripts/openstack-auth-proxy.py   # the Keystone-auth reverse proxy
  templates/
    configmap-*.yaml          # bundle each OAS into a ConfigMap
    rd-*.yaml                 # one RestDefinition per resource (toggle via values)
    auth-bridge-*.yaml        # the auth proxy Deployment/Service/ConfigMap
  samples/                    # example CRs (identity + federation)
compositiondefinition.yaml    # registers the chart as a Krateo Composition
examples/                     # the OKF example: the Composition CR
docs/                         # this bundle
```
