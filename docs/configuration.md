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
| `group` | `IdentityGroup` | `true` |
| `group_role_assignment` | `IdentityGroupRoleAssignment` | `true` |
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

`IdentityGroup` was here until 0.3.0: it is now modelled flat (see [api](api.md)) and on by default.

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
forwards to the discovered `identity` endpoint. Every key below has a default, so the schema
requires none of them: a Composition may omit `authBridge` entirely (see the 0.3.0 note in
[log](log.md)).

| Key | Type | Default | Effect |
|---|---|---|---|
| `enabled` | bool | `true` | Deploy the auth-bridge Deployment/Service/ConfigMap. |
| `replicaCount` | int | `1` | Proxy replica count. |
| `cloudsSecret` | string | `keystone-clouds` | Name of the Secret holding `clouds.yaml` (key `clouds.yaml`), created out-of-band. |
| `openrcSecret` | string | `""` | A Secret of `OS_*` variables (e.g. the OpenStack blueprint's `keystone-keystone-admin`) in the release namespace. When set it replaces `cloudsSecret`: the proxy mounts it and uses openstacksdk's `envvars` cloud. |
| `credentialRetrySeconds` | int | `300` | Seconds before the proxy retries credentials Keystone rejected; until then, or until the Secret changes, requests get 503 without reaching Keystone. |
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

**Credential rotation.** Both Secrets are mounted and re-read while the proxy runs: when the
password in them changes (e.g. the OpenStack blueprint rotating the Keystone admin password on
upgrade), the proxy rebuilds its session within the kubelet's Secret sync, about a minute, with no
restart. If Keystone rejects the credentials, the proxy answers 503 with the reason and does **not**
ask Keystone again with the same credentials until `credentialRetrySeconds` passes: retrying a stale
password on every request is what locks a Keystone account.

**Health.** `GET /_bridge/ready` is the readiness probe: 200 once the proxy serves, whatever Keystone
thinks of the credentials, so the Service keeps its endpoints and an identity failure is reported as
one (a 503 naming the rejected credentials) rather than as "connection refused". `GET /_bridge/auth`
answers 200 when the current credentials yield a token and 503 when they do not, with
`{state, error, credentials}` (a fingerprint prefix, never the secret).

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
