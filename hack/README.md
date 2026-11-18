# hack/

CI gates and helpers. `.github/workflows/lint.yaml` runs the gating ones on every pull request.

## validate-findby-identifiers.py

This gate refuses a findby that cannot match or cannot run. It also reports, for every kind with a
create and a get addressable from required spec fields, whether that get can tell
"not yet created" from "created". If it can't, the create never runs. Its assumptions are in the
script's docstring; the repository's minimum oasgen-provider is read from the top-level README.

A declaration counts as evidence only when rest-dynamic-controller **acts** on it. Each one, with the
code that consumes it (oasgen-provider tag 0.80.0, `go/rest-dynamic-controller` unless noted; the
standalone rest-dynamic-controller repository stops at 0.20.0):

| Declaration on the get verb | Verdict | Consumed at |
|---|---|---|
| `notFoundBody` | passes (functional) | `internal/controllers/restResources.go:663`, helpers `existence.go:139-150`; declared in oasgen-provider `apis/restdefinitions/v1alpha1/types.go:777` |
| `notFoundCodes` | passes (functional) | `internal/tools/client/restclient.go:371-376`, which remaps to a not-found error; declared in `types.go:764` |
| a `404` in the OAS responses | **not evidence** | absence comes from the wire status, `internal/tools/client/validators.go:148-150`. Declared responses only build the 2xx success set (`clienttools.go:75-88`, `restclient.go:389,399`) |
| `tolerateCodes` with 404 | **WARNING** | `restclient.go:381-383` turns it into an empty success, read as exists and up to date (`restResources.go:681-700`), so a deletion is masked |
| annotation `kog.openstack.krateo.io/get-absent-evidence` | passes as **asserted, with evidence**; an empty value is refused | the gate itself, which reads the vendor citation you write there |

### What the evidence annotation is, and is not

`get-absent-evidence` is **an author's citation**. The gate checks that it is present and well formed,
never that it is true, and it can go stale when the vendor refactors. So:
- **Name the tag** the citation was read at, such as `keystone stable/2026.1 keystone/api/projects.py
  L396-417`, so it can be re-checked. A value with no tag-shaped token (a `stable/<series>`, a version
  like `2026.1` or `29.1.1`, or a commit hash) is refused.
- **Re-verification is a periodic human or scheduled task**, never a network fetch inside the gate. A
  gate that fetched vendor source would fail closed on a network blip, and pass on a 404 page.

### The oasgen-provider minimum is a floor

The README's `oasgen-provider >= X.Y.Z` is checked as a floor: any minimum at or above 0.52.0 is
accepted. It is never an equality, so a repository pinned to exactly one version keeps being screened
when its pin moves. The self-test pins this: 0.52.0, 0.53.0 and 1.0.0 pass, 0.51.0 fails.

## Other gates

- `check-schema-required.py`: no `required` key in values.schema.json that values.yaml defaults.
- `test-auth-bridge.py`: the auth-bridge against a fake Keystone.
- `validate-docs-no-published-credentials.py`: no OpenStack-Helm published password in the docs.
