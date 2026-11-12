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

## `IdentityGroup` and `IdentityGroupRoleAssignment` (0.3.0)

`IdentityGroup` is a flat resource: `spec.name`, `spec.domain` (a domain **name**, resolved to its
id by a lookup) and `spec.description`. Keystone's `{"group": {...}}` envelope is added by the
RestDefinition's `requestTransform` and removed by its `responseTransform`, so it is never part of
the schema. `status.id` and `status.domain_id` are Keystone's. An update never sends the domain:
Keystone refuses to move a group between domains.

`IdentityGroupRoleAssignment` grants one role to one group on one project, all addressed by name
(`project`, `projectDomain`, `group`, `groupDomain`, `role`); lookups resolve the ids into the path
of Keystone's check (`GET`, 204/404), grant (`PUT`) and revoke (`DELETE`). Changing any field is a
different assignment: delete the resource and create a new one.

Both need oasgen-provider >= 0.58.0, where a path or query parameter supplied by a lookup is no
longer a required spec field (#555).

Measured on GKE against Keystone 2025.1 (OpenStack blueprint 0.3.47), oasgen-provider 0.59.0: a
group created in `Default` by name, a role granted to it on a project (check 204), a description
update applied with exactly one PATCH and no further writes over 200 s, revoke (check 404), and
deletion of the group and project.

