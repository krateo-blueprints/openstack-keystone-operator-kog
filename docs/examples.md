---
type: ExampleIndex
title: openstack-keystone-operator-kog — examples
description: Index of the runnable examples under examples/, plus the in-chart CR samples for identity and federation resources.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, examples]
timestamp: 2026-08-11T00:00:00Z
---

# Examples

## Composition

- [examples/composition](../examples/composition/README.md) — install the KOG operator
  (auth-bridge + enabled `RestDefinition`s) as a Krateo Composition, pointed at an
  in-cluster Keystone endpoint.

## In-chart CR samples

Applied after the operator's CRDs exist:

- `chart/samples/identity-resources.yaml` — example `Identity*` CRs: a
  `IdentityProjectConfiguration`, then `IdentityProject`, `IdentityUser`, `IdentityRole`,
  `IdentityRoleAssignment`, and `IdentityApplicationCredential`.
- `chart/samples/federation.yaml` — a full Keystone OS-FEDERATION trust as CRs:
  `IdentityFederationProvider`, `IdentityMapping`, and `IdentityFederationProtocol`
  (GitHub → Keycloak → Keystone → Horizon), validated live end-to-end.

See [quickstart.md](quickstart.md) for the guided walk-through and [usage.md](usage.md)
for the federation gotchas.
