---
type: API
title: openstack-keystone-operator-kog — API
description: The CompositionDefinition CRD this blueprint registers, the RestDefinition the chart emits per resource, and the shape of the generated Identity* / Identity*Configuration CRDs.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, compositiondefinition, restdefinition, crd]
timestamp: 2026-08-11T00:00:00Z
---

# API

Three layers of API are involved: the `CompositionDefinition` that registers this chart
as a Krateo Composition, the `RestDefinition`s the chart emits (one per enabled Keystone
resource), and the `Identity*` / `Identity*Configuration` CRDs Krateo generates from
them.

## `CompositionDefinition` (registration)

[`compositiondefinition.yaml`](../compositiondefinition.yaml) registers the published
chart as an installable Krateo Composition. `metadata.name` is the marketplace join key
and must match the chart name in `chart/Chart.yaml`.

- **Group / Version / Kind:** `core.krateo.io/v1alpha1`, `CompositionDefinition`
- **Spec:**

| Field | Type | Description |
|---|---|---|
| `spec.chart.url` | string | OCI URL of the published chart — `oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog`. |
| `spec.chart.version` | string | Chart version to install. |

Applying it makes Krateo derive a Composition Kind from the chart name. Per the crdgen
convention the Composition CR is:

- **Group:** `composition.krateo.io`
- **Version:** `v0-1-0` (derived from the chart version)
- **Kind:** `OpenstackKeystoneOperatorKog` (PascalCase of the CD name, hyphens removed)

Its `spec` mirrors the chart values (`authBridge`, `restdefinitions`) — see
[examples/composition](../examples/composition/README.md) and
[configuration.md](configuration.md).

## `RestDefinition` (emitted per resource)

Each enabled resource renders one `RestDefinition` (`templates/rd-<res>.yaml`):

- **Group / Version / Kind:** `ogen.krateo.io/v1alpha1`, `RestDefinition`
- **Key spec fields:**

| Field | Description |
|---|---|
| `spec.oasPath` | `configmap://<ns>/<release>-<res>/<file>.yaml` — the OAS subset bundled by `configmap-<res>.yaml`. |
| `spec.resourceGroup` | API group of the generated CRD (`identity.openstack.krateo.io`). |
| `spec.resource.kind` | The generated Kind (`Identity*`). |
| `spec.resource.identifiers` | Fields that identify the object (e.g. `project.id`, `project.name`). |
| `spec.resource.additionalStatusFields` | Extra fields surfaced on `.status` (e.g. `project.id`, `project.domain_id`). |
| `spec.resource.verbsDescription[]` | One entry per verb: `action`, `method`, `path`, and `requestFieldMapping` (path param ↔ CR field). |

Example (`IdentityProject`): CRUD verbs `create POST /projects`, `get GET /projects/{id}`,
`update PATCH /projects/{id}`, `delete DELETE /projects/{id}`, with `{id}` mapped from
`status.project.id`.

`IdentityRoleAssignment` is modeled as an idempotent action, not CRUD: `findby GET
/role_assignments` (with `identifiersMatchPolicy: AND`), `create PUT
/projects/{project_id}/users/{user_id}/roles/{role_id}`, and the matching `delete` —
`project_id`/`user_id`/`role_id` mapped from `spec.*`.

Federation resources use a client-chosen id in the path (`PUT`), and their `update` verb
is `PATCH` because Keystone's `PUT /OS-FEDERATION/.../{id}` is create-only (returns 409 if
the object exists).

## Generated `Identity*` CRDs

`oasgen-provider` reads each `RestDefinition` and generates two CRDs:

- **`Identity<Res>`** — group `identity.openstack.krateo.io`, version `v1alpha1`. Its
  `spec` is the OAS request schema wrapped in the Keystone envelope (`spec.project.*`,
  `spec.user.*`, …) plus a `configurationRef`. Its `status` carries the identifiers and
  `additionalStatusFields` (e.g. `status.project.id`).
- **`Identity<Res>Configuration`** — carries the bearer token (from the OAS `http`/`bearer`
  security scheme) via `spec.authentication.bearer.tokenRef`. Because the auth-bridge
  injects the real `X-Auth-Token`, the referenced token value is a placeholder. Create one
  `Configuration` per Kind you use.

Kinds and their Keystone endpoints are listed in [overview.md](overview.md#the-resource-set).
For the per-field request shapes, read the OAS subsets in `chart/assets/` (e.g.
`chart/assets/project.yaml`).
