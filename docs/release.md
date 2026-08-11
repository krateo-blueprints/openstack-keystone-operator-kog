---
type: Runbook
title: openstack-keystone-operator-kog — release
description: How a release ships — a plain-SemVer tag matching Chart.yaml drives the release-chart workflow to lint, package, and push the chart to the GHCR OCI charts namespace the CompositionDefinition points at.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, release, oci, ghcr]
timestamp: 2026-08-11T00:00:00Z
---

# Release

A release publishes the Helm chart to
`oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog` — the artifact
the `CompositionDefinition`'s `spec.chart.url` points at.

## Cut a release

1. Bump `version` (and `appVersion`) in `chart/Chart.yaml` to the new SemVer.
2. Commit and push to the default branch.
3. Tag with the **plain SemVer** (no `v` prefix) that matches `Chart.yaml` `version`:

   ```bash
   git tag 0.2.0
   git push origin 0.2.0
   ```

The [`release-chart`](../.github/workflows/release-chart.yaml) workflow runs on any tag
matching `[0-9]+.[0-9]+.[0-9]+` (or a manual `workflow_dispatch`). It:

1. installs Helm,
2. runs `helm lint chart` (which also validates `values.schema.json`),
3. verifies the git tag equals `Chart.yaml` `version` (fails otherwise),
4. `helm package chart` — note `helm package` does **not** render templates, so a chart
   that needs runtime input still publishes,
5. logs in to GHCR with the workflow token, and
6. `helm push`es the `.tgz` to `oci://ghcr.io/<owner>/charts` (with retry for GHCR
   first-push flakiness).

## After publishing

Update the consuming `CompositionDefinition`'s `spec.chart.version` (and the `pin` in
`docs/llms.txt`) to the new version so installs resolve the freshly pushed artifact.

> The chart lint job in [`lint.yaml`](../.github/workflows/lint.yaml) runs the shared
> `lint-docs` workflow on every push/PR — keep the OKF doc bundle green (all
> `docs/**/*.md` and `examples/**/*.md` carry frontmatter, every relative link resolves).
