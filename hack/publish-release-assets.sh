#!/usr/bin/env bash
# Attach files to the GitHub release for a tag, creating the release if nobody has yet.
#
# Usage: [RELEASE_NOTES="..."] publish-release-assets.sh <tag> <file>...
# RELEASE_NOTES is the body used only if this script is the one that creates the release.
#
# WHY THIS IS NOT `gh release view || gh release create`. A tag push starts TWO workflows that both
# want the release: release-tag (this one, to attach the stamped CompositionDefinition) and
# release-notes (the org reusable, which creates the release to write its body). With view-then-create,
# release-tag can see "no release" and then lose the create to release-notes a moment later, and the
# step dies on `HTTP 422 ... Release.tag_name already exists` -- with the chart already pushed and only
# the CompositionDefinition asset missing. That is how glance-kog 0.1.2 failed; keystone-kog 0.4.2 won
# the same race by luck.
#
# So the create is tried, and if it fails the release is LOOKED UP AGAIN: if it exists now, someone
# else created it, which is all this step ever needed. ANY OTHER create failure (a 403, a 5xx, a
# typo'd tag) leaves the release absent and still fails the step, and so does a failed upload.
# Never `|| true` on the whole thing.
#
# WHY A RE-LOOKUP RATHER THAN MATCHING "already exists". The first version of this grepped GitHub's
# 422 text. That works until GitHub rephrases it, and the test could never catch that, because the
# test supplies the wording through its stand-in `gh` -- so the script and the test would stay green
# together while the race came back. The re-lookup tests the only thing the step cares about, which
# is whether the release exists, and it is independent of the message, the locale and the HTTP code.
set -euo pipefail
tag="${1:?usage: publish-release-assets.sh <tag> <file>...}"; shift
[ "$#" -gt 0 ] || { echo "publish-release-assets: no files to attach" >&2; exit 2; }
notes="${RELEASE_NOTES:-Apply the attached CompositionDefinition to register this version.}"

if gh release view "$tag" >/dev/null 2>&1; then
  echo "release $tag exists"
elif out="$(gh release create "$tag" --title "$tag" --notes "$notes" 2>&1)"; then
  echo "created release $tag"
elif gh release view "$tag" >/dev/null 2>&1; then
  echo "release $tag was created concurrently (release-notes runs on the same tag push); attaching to it"
  printf 'the create we lost said: %s\n' "$out" >&2
else
  printf '%s\n' "$out" >&2
  echo "publish-release-assets: creating release $tag failed and the release does not exist" >&2
  exit 1
fi
gh release upload "$tag" "$@" --clobber
echo "attached to $tag: $*"
