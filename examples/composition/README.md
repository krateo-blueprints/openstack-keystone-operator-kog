---
type: Example
title: composition — install the Keystone KOG operator as a Krateo Composition
description: A ready-to-apply Composition CR that installs the openstack-keystone-operator-kog operator — the auth-bridge plus the enabled per-resource RestDefinitions — pointed at an in-cluster Keystone endpoint.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [example, krateo, kog, keystone, composition]
timestamp: 2026-08-11T00:00:00Z
---

# composition

[`composition.yaml`](composition.yaml) is the Composition CR that installs the KOG
**operator**: the auth-bridge proxy plus the enabled per-resource `RestDefinition`s
(which generate the `Identity*` CRDs). It does **not** create individual Keystone objects
— the per-resource CRs (`IdentityProject` / `IdentityUser` / …) live in
`chart/samples/identity-resources.yaml` and are applied after the CRDs exist.

The `apiVersion`/`Kind` follow the Krateo crdgen convention derived from the chart name
and version: group `composition.krateo.io`, version `v0-1-0`, Kind
`OpenstackKeystoneOperatorKog`.

## Prerequisites

- The KOG provider (`oasgen-provider`) installed — see [usage.md](../../docs/usage.md).
- The `CompositionDefinition` applied so Krateo knows the Composition Kind:

  ```bash
  kubectl apply -f ../../compositiondefinition.yaml
  ```

- A Secret named by `authBridge.cloudsSecret` (here `keystone-clouds`) holding
  `clouds.yaml`:

  ```bash
  kubectl -n krateo-system create secret generic keystone-clouds \
    --from-file=clouds.yaml=clouds.yaml
  ```

## Apply

```bash
kubectl apply -f composition.yaml
kubectl -n krateo-system get restdefinitions.ogen.krateo.io -w
```

Edit `spec.authBridge.upstreamEndpoint` to point at your Keystone identity endpoint, and
flip entries under `spec.restdefinitions` to choose which `Identity*` CRDs are emitted.
The full values surface is documented in [configuration.md](../../docs/configuration.md).
