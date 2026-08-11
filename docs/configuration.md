---
type: Configuration
title: openstack-keystone-operator-kog — configuration
description: The whole chart values surface — per-resource RestDefinition toggles and the auth-bridge config — typed by values.schema.json, plus the two resources disabled by default and why.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, values, auth-bridge, restdefinitions]
timestamp: 2026-08-11T00:00:00Z
---

# Configuration

Everything is `chart/values.yaml`, fully typed by `chart/values.schema.json` (the same
schema Krateo derives the Composition input form from). There are two blocks:
`restdefinitions` (which resources to emit) and `authBridge` (how to reach Keystone).

## `restdefinitions` — per-resource toggles

One entry per Keystone resource. Each entry has:

| Key | Type | Default | Effect |
|---|---|---|---|
| `enabled` | bool | see below | Emit this resource's `RestDefinition` (and so its CRD). |
| `resourceGroup` | string | `identity.openstack.krateo.io` | API group for the generated CRD. |
| `resourceKind` | string | `Identity<Res>` | Kind for the generated CRD. |

Defaults per resource:

| Entry | `resourceKind` | `enabled` |
|---|---|---|
| `project` | `IdentityProject` | `true` |
| `user` | `IdentityUser` | `true` |
| `role` | `IdentityRole` | `true` |
| `domain` | `IdentityDomain` | `true` |
| `role_assignment` | `IdentityRoleAssignment` | `true` |
| `group` | `IdentityGroup` | `false` |
| `application_credential` | `IdentityApplicationCredential` | `false` |
| `identity_provider` | `IdentityFederationProvider` | `true` |
| `mapping` | `IdentityMapping` | `true` |
| `federation_protocol` | `IdentityFederationProtocol` | `true` |

Toggle only what you need, e.g. to disable federation:

```yaml
restdefinitions:
  identity_provider:
    enabled: false
  mapping:
    enabled: false
  federation_protocol:
    enabled: false
```

### Disabled-by-default resources

- **`group` (`IdentityGroup`) — off.** crdgen currently emits an undefined Go type `Group`
  for the `group` envelope property and fails CRD generation (`unknown type Group`),
  whether the schema is `$ref`'d or inlined — the literal property name `group` is the
  trigger. Needs an upstream crdgen fix; the OAS and `RestDefinition` ship ready to enable
  once that lands.
- **`application_credential` (`IdentityApplicationCredential`) — off.** Create is
  `POST /v3/users/{user_id}/application_credentials` with a body of strictly
  `{application_credential:{…}}`, but KOG sends the whole spec, so the path-only `user_id`
  leaks into the body and Keystone returns **400**. The CRD generates and `get`/`delete`
  work; clean create needs a KOG exclude-from-body mapping (the same caveat as Nova's quota
  set). App credentials are the production answer to expiring tokens, so this is the
  highest-value follow-up.

## `authBridge`

The auth-bridge is a stateless Keystone-auth reverse proxy (openstacksdk). The generated
controller's plain-HTTP calls go here; the proxy injects a fresh `X-Auth-Token` and
forwards to the discovered `identity` endpoint. `authBridge` is **required** by the schema.

| Key | Type | Default | Effect |
|---|---|---|---|
| `enabled` | bool | `true` | Deploy the auth-bridge Deployment/Service/ConfigMap. |
| `replicaCount` | int | `1` | Proxy replica count. |
| `cloudsSecret` | string | `keystone-clouds` | Name of the Secret holding `clouds.yaml` (key `clouds.yaml`), created out-of-band. |
| `osCloud` | string | `openstack` | Cloud name inside `clouds.yaml`. |
| `serviceType` | string | `identity` | Catalog service type to proxy. |
| `osInterface` | string | `internal` | Catalog interface to discover. |
| `upstreamEndpoint` | string | `""` | Override the discovered endpoint, e.g. `http://keystone-api.openstack.svc.cluster.local:5000/v3`. |
| `image.repository` | string | `quay.io/airshipit/openstack-client` | Proxy image (ships the openstacksdk + the proxy script). |
| `image.tag` | string | `2026.1-ubuntu_noble` | Image tag. |
| `image.pullPolicy` | string | `IfNotPresent` | Image pull policy. |
| `service.type` | string | `ClusterIP` | Proxy Service type. |
| `service.port` | int | `8080` | Proxy Service port. |
| `resources` | object | `20m/64Mi` → `500m/256Mi` | Proxy container requests/limits. |
| `podAnnotations` | object | `{}` | Extra pod annotations. |
| `nodeSelector` / `tolerations` / `affinity` | | `{}` / `[]` / `{}` | Standard scheduling. |

Supply `clouds.yaml` out-of-band (it is never templated by the chart):

```bash
kubectl -n krateo-system create secret generic keystone-clouds --from-file=clouds.yaml=clouds.yaml
```

## Top-level

| Key | Type | Default | Effect |
|---|---|---|---|
| `serviceAccount.create` | bool | `false` | Create a ServiceAccount for the auth-bridge. |
| `serviceAccount.name` | string | `""` | Use an existing ServiceAccount name. |
| `nameOverride` | string | `""` | Override the chart name in resource names. |
| `fullnameOverride` | string | `""` | Override the fully-qualified name. |
