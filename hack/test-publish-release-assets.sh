#!/usr/bin/env bash
# Exercise hack/publish-release-assets.sh against a stand-in `gh` (no network, no GitHub token).
# Each case scripts what `release view` and `release create` answer and asserts the exit code and
# whether `release upload` was reached. The race case is the one that broke glance-kog 0.1.2.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
script="$here/publish-release-assets.sh"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"; echo "cd" > "$work/cd.yaml"
cat > "$work/bin/gh" <<'GH'
#!/usr/bin/env bash
# Stand-in gh: behaviour from env, every call logged.
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "release view")
    # `absent_then_present` is the race as it actually happens: our first look sees nothing, the other
    # workflow creates the release, and our second look finds it. A counter file, because the stand-in
    # is a fresh process per call. The old `absent` case modelled the race as "never exists", which is
    # not the world -- and the grep version passed it only because it never looked twice.
    if [ "$VIEW" = absent_then_present ]; then
      n=$(cat "$GH_VIEWS" 2>/dev/null || echo 0); echo $((n+1)) > "$GH_VIEWS"
      [ "$n" -ge 1 ] && exit 0 || { echo "release not found" >&2; exit 1; }
    fi
    [ "$VIEW" = present ] && exit 0 || { echo "release not found" >&2; exit 1; } ;;
  "release create")
    case "$CREATE" in
      ok)     exit 0 ;;
      exists) echo 'HTTP 422: Validation Failed (https://api.github.com/repos/o/r/releases)' >&2
              echo 'Release.tag_name already exists' >&2; exit 1 ;;
      403)    echo 'HTTP 403: Resource not accessible by integration (https://api.github.com/repos/o/r/releases)' >&2; exit 1 ;;
      reworded) echo 'HTTP 422: a tag release already present for this ref' >&2; exit 1 ;;
    esac ;;
  "release upload") [ "${UPLOAD:-ok}" = ok ] && exit 0 || { echo "HTTP 500: upload failed" >&2; exit 1; } ;;
esac
echo "unexpected gh call: $*" >&2; exit 99
GH
chmod +x "$work/bin/gh"

fail=0
run() {  # label VIEW CREATE UPLOAD want_exit want_upload(yes|no)
  local label="$1"; export VIEW="$2" CREATE="$3" UPLOAD="$4" GH_LOG="$work/log" GH_VIEWS="$work/views"
  : > "$GH_LOG"; rm -f "$GH_VIEWS"
  PATH="$work/bin:$PATH" bash "$script" 1.2.3 "$work/cd.yaml" >"$work/out" 2>&1; local rc=$?
  local uploaded=no; grep -q '^release upload' "$GH_LOG" && uploaded=yes
  local exit_ok=no
  if [ "$5" = 0 ]; then [ "$rc" = 0 ] && exit_ok=yes; else [ "$rc" != 0 ] && exit_ok=yes; fi
  if [ "$exit_ok" = yes ] && [ "$uploaded" = "$6" ]; then
    echo "ok    $label (exit $rc, upload=$uploaded)"
  else
    echo "FAIL  $label: exit $rc (want $5), upload=$uploaded (want $6)"; sed 's/^/      /' "$work/out"; fail=1
  fi
}
run "release already there"                                  present ok     ok   0  yes
run "nobody created it yet"                                  absent  ok     ok   0  yes
run "RACE: first look absent, create loses, second look finds it" absent_then_present exists ok 0 yes
# THE POINT OF THE RE-LOOKUP: a create that fails with wording this test does NOT recognise, where
# the release exists by the time we look again, must still succeed. The grep version failed this,
# and no test could have caught that, because the test supplies the wording.
run "RACE with a REWORDED 422: re-lookup finds it"           absent_then_present reworded ok 0 yes
run "create fails, release still absent -> fail, no upload"  absent  reworded ok   1  no
run "real create failure (403) still fails, no upload"       absent  403    ok   1  no
run "upload failure still fails"                             present ok     fail 1  yes
# RELEASE_NOTES reaches the create call when set.
export VIEW=absent CREATE=ok UPLOAD=ok GH_LOG="$work/log"; : > "$GH_LOG"
RELEASE_NOTES="custom notes 1.2.3" PATH="$work/bin:$PATH" bash "$script" 1.2.3 "$work/cd.yaml" >/dev/null 2>&1
if grep -q -- '--notes custom notes 1.2.3' "$GH_LOG"; then echo "ok    RELEASE_NOTES is passed to the create"
else echo "FAIL  RELEASE_NOTES was not passed to the create"; sed 's/^/      /' "$GH_LOG"; fail=1; fi
# Self-check 2: the FIRST fix (grep for "already exists") must FAIL the reworded race, or replacing it
# with a re-lookup bought nothing. A change no case can distinguish from its predecessor is not a
# change worth making.
cat > "$work/grepver.sh" <<'GREPVER'
set -euo pipefail
if gh release view "$1" >/dev/null 2>&1; then :
elif out="$(gh release create "$1" --title "$1" --notes x 2>&1)"; then :
elif printf '%s' "$out" | grep -qi 'already exists'; then :
else exit 1; fi
gh release upload "$1" "$2" --clobber
GREPVER
export VIEW=absent_then_present CREATE=reworded UPLOAD=ok GH_LOG="$work/log" GH_VIEWS="$work/views"
: > "$GH_LOG"; rm -f "$GH_VIEWS"
if PATH="$work/bin:$PATH" bash "$work/grepver.sh" 1.2.3 "$work/cd.yaml" >/dev/null 2>&1; then
  echo "FAIL  self-check 2: the grep version passed the reworded race, so the re-lookup changed nothing"; fail=1
else
  echo "ok    self-check 2: the grep version fails the reworded race"
fi

# Self-check: the OLD step (view || create; upload under set -e) must fail the race case, or this
# test could not tell the fix from the bug.
cat > "$work/old.sh" <<'OLD'
set -euo pipefail
gh release view "$1" >/dev/null 2>&1 || gh release create "$1" --title "$1" --notes x
gh release upload "$1" "$2" --clobber
OLD
export VIEW=absent CREATE=exists UPLOAD=ok GH_LOG="$work/log"; : > "$GH_LOG"
if PATH="$work/bin:$PATH" bash "$work/old.sh" 1.2.3 "$work/cd.yaml" >/dev/null 2>&1; then
  echo "FAIL  self-check: the old view||create step passed the race case, so this test detects nothing"; fail=1
else
  echo "ok    self-check: the old view||create step fails the race case"
fi
exit $fail
