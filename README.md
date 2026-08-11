<p align="center">
  <img src="docs/krateo-loves-keystone.png" alt="Krateo loves OpenStack Keystone" width="900"/>
</p>

# openstack-keystone-operator-kog

A Krateo Operator Generator (KOG) blueprint that turns **OpenStack Keystone (identity
v3)** resources into native Kubernetes custom resources.

## What is this

There is no hand-written controller: a hand-curated OpenAPI subset per resource plus
Krateo's generic [`oasgen-provider`](https://github.com/krateo-platformops/oasgen-provider)
and [`rest-dynamic-controller`](https://github.com/krateo-platformops/rest-dynamic-controller)
reconcile each CR into a real Keystone object. `kubectl apply` an `IdentityProject` /
`IdentityUser` / `IdentityRole` / … and it becomes a Keystone object.

Because the controller speaks plain HTTP and cannot do Keystone token exchange, the chart
ships an **auth-bridge**: an openstacksdk reverse proxy that authenticates with an admin
`clouds.yaml` and injects a **fresh** `X-Auth-Token` on every call (auto-refreshing,
in-cluster). The resource set spans projects, users, roles, domains, role assignments, and
the OS-FEDERATION trust (external OIDC/SAML IdP → Keystone), with `IdentityGroup` and
`IdentityApplicationCredential` shipped disabled behind documented crdgen/body-leak
caveats.

Full picture: [docs/index.md](docs/index.md) and [docs/overview.md](docs/overview.md).

## Install

Prereq — Krateo's KOG provider and a `clouds.yaml` Secret:

```bash
helm repo add krateo https://charts.krateo.io && helm repo update
helm upgrade --install oasgen-provider krateo/oasgen-provider -n krateo-system --create-namespace
kubectl -n krateo-system create secret generic keystone-clouds --from-file=clouds.yaml=clouds.yaml
```

Then either as a Helm chart:

```bash
helm upgrade --install keystone-kog ./chart -n krateo-system \
  --set authBridge.upstreamEndpoint=http://keystone-api.openstack.svc.cluster.local:5000/v3
```

…or as a Krateo Composition:

```bash
kubectl apply -f compositiondefinition.yaml
kubectl apply -f examples/composition/composition.yaml
```

Details and the `clouds.yaml` shape: [docs/usage.md](docs/usage.md).

## Configure

Everything is `chart/values.yaml`, typed by `chart/values.schema.json`. Most used:

| Setting | Default | Effect |
|---|---|---|
| `authBridge.upstreamEndpoint` | `""` | The in-cluster Keystone identity endpoint (the key user input). |
| `authBridge.cloudsSecret` | `keystone-clouds` | Secret holding `clouds.yaml` (created out-of-band). |
| `restdefinitions.<res>.enabled` | per-resource | Toggle which `Identity*` CRDs are emitted. |

`IdentityGroup` and `IdentityApplicationCredential` are off by default; `IdentityDomain`
must be disabled before it can be deleted. Full surface:
[docs/configuration.md](docs/configuration.md).

## Examples

- [examples/composition](examples/composition/README.md) — install the operator as a
  Krateo Composition.
- `chart/samples/identity-resources.yaml` — example `Identity*` CRs.
- `chart/samples/federation.yaml` — a full OS-FEDERATION trust as CRs (validated live,
  GitHub → Keycloak → Keystone → Horizon).

Guided walk-through with a Horizon screenshot: [docs/quickstart.md](docs/quickstart.md).

## Docs

- [docs/index.md](docs/index.md) — the map
- [docs/overview.md](docs/overview.md) — architecture: KOG pipeline, `Identity*` naming, the auth-bridge, federation
- [docs/usage.md](docs/usage.md) — install (Helm or Composition), the `clouds.yaml` Secret, the first CR, federation gotchas
- [docs/configuration.md](docs/configuration.md) — the whole values surface
- [docs/api.md](docs/api.md) — the `CompositionDefinition`, `RestDefinition`, and generated `Identity*` CRDs
- [docs/examples.md](docs/examples.md) — examples index
- [docs/release.md](docs/release.md) — how a release ships
- [docs/log.md](docs/log.md) — curated history
- [docs/quickstart.md](docs/quickstart.md) — install and see a resource in Horizon

## Develop & release

`helm lint chart` locally (it also validates `values.schema.json`). A plain-SemVer tag
(`X.Y.Z`, **no** `v` prefix) matching `chart/Chart.yaml` `version` triggers the
[`release-chart`](.github/workflows/release-chart.yaml) workflow, which packages and pushes
the chart to `oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog` — the
artifact the `CompositionDefinition` points at. Release runbook:
[docs/release.md](docs/release.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).
