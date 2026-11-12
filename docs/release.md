---
type: Runbook
title: openstack-keystone-operator-kog — release
description: How a release ships — a plain-SemVer git tag on a commit that passed lint publishes the chart to GHCR OCI and to the Marketplace blueprints index, with the CompositionDefinition stamped to the tag inside the archive and on the GitHub release.
resource: oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog
tags: [krateo, kog, keystone, release, oci, ghcr, marketplace]
timestamp: 2026-11-12T00:00:00Z
---

# Release

One plain-SemVer git tag (`X.Y.Z`, **no** `v` prefix) publishes the chart. Nothing is bumped by
hand: `version: CHART_VERSION` in `helm/openstack-keystone-operator-kog/Chart.yaml` and
`spec.chart.version: CHART_VERSION` in the root `compositiondefinition.yaml` are stamped from the
tag. `appVersion` is the Keystone release the chart is validated against, not the chart version.

## Cut a release

1. Merge the change to `main`. [`lint.yaml`](../.github/workflows/lint.yaml) runs on the merge
   commit (it runs on every push to `main`).
2. Wait until that **whole** lint run has concluded successfully, then tag the merge commit:

   ```bash
   git tag X.Y.Z <merge-sha>
   git push origin X.Y.Z
   ```

## What a tag ships

[`release-tag.yaml`](../.github/workflows/release-tag.yaml), on a `[0-9]+.[0-9]+.[0-9]+` tag:

1. refuses the tag unless the tagged commit has a completed, successful run of `lint.yaml`;
2. stamps `CHART_VERSION` into `Chart.yaml` and the CompositionDefinition, and copies the stamped
   CompositionDefinition into the chart so the archive describes itself;
3. packages the chart and gates it for the Marketplace **blueprints** channel: `Chart.yaml`
   `sources` lists this repository, the archive carries `values.schema.json` and
   `compositiondefinition.yaml`, the CompositionDefinition installs this chart at this version,
   the icon is an https URL, and `keywords` is non-empty;
4. pushes it to `oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog` and checks
   that it is anonymously pullable (core-provider pulls anonymously);
5. attaches the stamped `compositiondefinition.yaml` to the GitHub release;
6. hands the same archive to the org publisher (`krateo-blueprints/charts`
   `publish-chart.yaml`), which adds it to
   `https://krateo-blueprints.github.io/charts/blueprints/index.yaml` and installs it from the served
   index before it reports success.

## After publishing

Check that the published archive and the index entry are the same bytes: pull
`oci://ghcr.io/krateo-blueprints/charts/openstack-keystone-operator-kog --version X.Y.Z`, then
compare its sha256 with the `digest` of the `X.Y.Z` entry in the blueprints index.

> The [`lint.yaml`](../.github/workflows/lint.yaml) workflow also runs the shared `lint-docs` job
> and the `values.schema.json` gate (`hack/check-schema-required.py`) on every pull request and
> every push to `main`. Keep both green: a tag on a commit whose lint run failed is refused.
