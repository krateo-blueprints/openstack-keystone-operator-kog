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

## Other gates

- `check-schema-required.py`: no `required` key in values.schema.json that values.yaml defaults.
- `test-auth-bridge.py`: the auth-bridge against a fake Keystone.
- `validate-docs-no-published-credentials.py`: no OpenStack-Helm published password in the docs.
