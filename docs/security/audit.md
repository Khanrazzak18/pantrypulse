# PantryPulse security audit (Stage 12)

Scope: the whole repository, git history, the running API and web app, the AWS account permissions of
`pantrypulse-dev`, and the Bedrock call paths. Method: gitleaks (history and tree), bandit, pip-audit,
npm audit, a manual review of every raw SQL statement, automated role-by-route and fuzz tests, header
and CSP checks in a real browser, and one live prompt-injection run against the real model.

OWASP categories are from the Top 10 (2021) and the Top 10 for LLM Applications (LLM01..LLM10, 2025).
"Test" names the automated test that now fails if the fix is removed.

## Summary

| Severity | Found | Fixed | Accepted / open |
| --- | --- | --- | --- |
| High | 4 | 4 | 0 |
| Medium | 10 | 8 | 2 accepted (SEC-14 CSP styles, SEC-17 dev-only npm advisory) |
| Low | 8 | 3 fixed, 2 verified | 2 accepted (SEC-15, SEC-20), 1 open (SEC-16) |
| Process | 3 | 3 (key rotated, scanning added) | 0 |

## Findings

| ID | Category | Severity | Where | Evidence | Fix | Test | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SEC-01 | A07 Identification and Authentication Failures | High | `app/auth`, `api/auth.py` | Logout only cleared the cookie; a copied `pp_session` token stayed valid for 8 hours. Deactivating a user was the only revocation. | `users.token_version`; the JWT carries `ver`; a token is valid only while it equals the current version. Logout and changes to `is_active`, `role`, `pantry_id` or `password_hash` bump it (ORM listener). Migration 0007. | `test_token_revocation.py`, `test_auth_tokens.py`, E2E SEC-06, SEC-07 | Fixed |
| SEC-02 | A01 Broken Access Control | High | `frontend/src/proxy.ts` | `/admin` was not in the proxy matcher, so a logged-out visitor was not redirected (the page rendered its shell before the API call failed). | Matcher covers every page; logged-out visitors are redirected from `/coordinator`, `/pantry`, `/admin`. | E2E SEC-08 | Fixed |
| SEC-03 | A01 Broken Access Control | High | all routes | No test proved which role may call which route. | `test_authorization_matrix.py` walks the OpenAPI schema; every method and path must have an entry in an `ACCESS` table, and each role is tried against each route (401 anonymous, 403 wrong role, pantry managers limited to their own pantry). A new route without an entry fails the test. | `test_authorization_matrix.py` | Fixed |
| SEC-04 | A05 Security Misconfiguration (CSRF) | High | `app/security/http.py` | The cookie is `SameSite=Lax` only; there was no server-side check that state-changing requests come from the app. | Origin middleware: a present `Origin` must be an allowed origin, a present `Sec-Fetch-Site` must be `same-origin` or `none`; requests with neither header (curl, scripts) pass because they carry no ambient cookie. | `test_csrf_origin.py`, E2E SEC-09, SEC-10 | Fixed |
| SEC-05 | A05 Security Misconfiguration | Medium | web and API responses | No CSP, frame-ancestors, nosniff, Referrer-Policy or Permissions-Policy; `X-Powered-By` was sent. | `proxy.ts` sets a per-request nonce CSP with `strict-dynamic` (no `'unsafe-inline'` for scripts), frame-ancestors `'none'`, nosniff, Referrer-Policy, Permissions-Policy; HSTS and `upgrade-insecure-requests` only when `COOKIE_SECURE=true`. The API adds its own headers. `poweredByHeader` off. | `test_security_headers.py`, E2E SEC-01..SEC-04 | Fixed (see SEC-14) |
| SEC-06 | LLM10 Unbounded Consumption / A04 Insecure Design | Medium | upload and AI routes | Any signed-in coordinator could trigger unlimited Bedrock calls (cost and denial of service). | Per-user hourly limits kept in Postgres (`rate_limits`, one upsert statement, hashed key): uploads 20, each AI endpoint 30, weekly refresh 6; configurable in `.env`. The role check runs before counting. Migration 0008. | `test_rate_limits.py` (a test per limit proves it triggers and returns 429 in the error envelope) | Fixed |
| SEC-07 | LLM10 Unbounded Consumption | Medium | `ai/llm_provider.py` | Token and time limits depended on the caller. | `MAX_OUTPUT_TOKENS` 4096 and `MAX_READ_TIMEOUT_SECONDS` 60 are clamped inside the provider; every call site passes explicit limits. | `test_llm_safety.py` | Fixed |
| SEC-08 | A05 Security Misconfiguration | Medium | `main.py` | `/api/docs` and `/api/openapi.json` were public. | Off unless `EXPOSE_API_DOCS=true`. | `test_security_headers.py` | Fixed |
| SEC-09 | A04 Insecure Design | Medium | `security/http.py` | Request bodies were read before size checks, so a huge body was buffered. | 413 `payload_too_large` from the declared `Content-Length` (1 MB for JSON, 11 MiB for uploads) before the body is read. The 10 MB file check remains. | `test_data_handling.py` | Fixed (a chunked body with no length is still bounded by the framework, see SEC-16) |
| SEC-10 | A09 Security Logging and Monitoring Failures | Medium | `db.py`, `logging.py` | A database error message could quote row values (for example "Key (email)=(...)") into logs. | `hide_parameters=True` on the engine and a log formatter that removes DETAIL, CONTEXT, HINT and parameter lines. | `test_log_hygiene.py` | Fixed |
| SEC-11 | A03 Injection (SQL) | Low | 20 `text()` calls | Every raw statement reviewed: all are constant strings except `scripts/seed.py` (table names built with f-strings from a fixed list) and `scripts/e2e_server.py` / `eval` (not on the request path). Bandit B608 flagged `seed.py`. | `seed.py` quotes identifiers through one `quote()` helper. All request-path code uses the ORM or bound parameters. An inventory test fails if a new raw statement appears. Injection payloads were added to the fuzz test, with a `pg_sleep` payload that must not delay a response, and row counts that must not change. | `test_sql_hygiene.py`, `test_api_fuzz.py` (49 cases), bandit | Fixed |
| SEC-12 | A02 Cryptographic Failures / A07 | Low | `scripts/seed.py` | The documented demo passwords are public. | `make seed` refuses them when `COOKIE_SECURE=true`. Demo passwords are in the README as local-only. | `test_seed.py` | Fixed |
| SEC-13 | A05 / least privilege (A01) | Medium | AWS user `pantrypulse-dev` | The user had `AmazonBedrockFullAccess`, later also `AmazonBedrockReadOnly` (found during verification). README's example policy included discovery actions. | Policy in `docs/security/iam-policy.json`: `bedrock:InvokeModel` only, on the Haiku 4.5 inference profile and its foundation models. Applied in the console (see evidence below). The README policy no longer has discovery actions. | `test_iam_policy.py` (policy pinned to the code) and a live check | Fixed |
| SEC-14 | A05 Security Misconfiguration | Medium | CSP `style-src` | **`style-src` still contains `'unsafe-inline'`.** Next.js and Recharts write inline `style` attributes, which a nonce cannot cover. Scripts do not use `'unsafe-inline'` (nonce plus `strict-dynamic`; `'unsafe-eval'` only in `next dev`). | Accepted. Style injection can restyle or exfiltrate through CSS but cannot run code; script execution is blocked by the policy. | E2E SEC-01 checks the policy on every page with no violations | Accepted risk |
| SEC-15 | A04 Insecure Design | Low | login lockout | The per-address login limit uses `X-Forwarded-For`, which a caller can forge. The per-email limit is the real protection. | Documented. A production proxy must set the header itself. | existing lockout tests | Accepted risk |
| SEC-16 | A04 Insecure Design | Low | uploads | AI work runs inside the request; a request with no `Content-Length` is bounded only by the framework. | Documented; production proxy limit recommended. | n/a | Open (production hardening) |
| SEC-17 | A06 Vulnerable and Outdated Components | Medium | `frontend` dev dependencies | `npm audit` reports 5 high in the `eslint-config-next` chain (`braces` <=3.0.3, GHSA-vfj7-8cjw-p6xm). No patched release exists; the only `--force` fix downgrades `eslint-config-next` to 14. `npm audit --omit=dev` reports 0 vulnerabilities. | Recorded in `docs/security/accepted-risks.json`; `make security` fails on any other high or critical advisory. pip-audit: no known vulnerabilities. | `test_audit_gate.py` | Accepted (dev-only) |
| SEC-18 | LLM01 Prompt Injection | Medium | intake, reasons, summaries | Manifests are untrusted text that reaches the model. | The text goes in the user turn inside `<manifest>` tags (a closing tag in the text is neutralised) and the system prompt says it is data. The model gets exactly one tool and is forced to call it; the tool only returns a list that is validated by Pydantic; a call to any other tool name is ignored. Nothing is written until a coordinator confirms. Live run against the real model with three injection manifests: all three produced only the legitimate item, no extra fields (`docs/security/injection-check.md`). | `test_llm_safety.py` (15 tests), `eval/injection_check.py` | Fixed |
| SEC-19 | LLM05 Improper Output Handling | Low | frontend | Model text is rendered in the UI. | React escapes text; there is no `dangerouslySetInnerHTML`. A hostile donor name, item name and notes render as text and no script runs. | E2E SEC-05, `test_llm_safety.py` | Fixed |
| SEC-20 | LLM02 Sensitive Information Disclosure | Low | `donations.raw_output` | The raw model output is stored as JSONB (needed for review and audit). Bedrock receives only the manifest and a date; no user, pantry or household data. | Checked by reading `build_content`: the model receives the manifest text (or image) and today's date only. The stored raw output is the tool input, the parsed result and token usage. Retention of old raw output is a policy decision for the food bank. | `test_llm_safety.py` (the manifest is the only user data sent) | Accepted (documented) |
| SEC-21 | A03 Injection (XSS), A08 Software and Data Integrity | Low | uploads | Files must be pdf, png, jpg, webp, txt, eml and at most 10 MB; the stored name is generated, the file type is checked against magic bytes (intake tests); no route serves stored files. | Verified by test; no change needed beyond SEC-09. | `test_data_handling.py` | Verified |
| SEC-22 | A02 Cryptographic Failures | Low | Postgres | Database port exposure. | Compose publishes Postgres on `127.0.0.1` only (checked by test). | `test_data_handling.py` | Verified |

## Process findings (secrets)

| ID | Finding | Evidence | Status |
| --- | --- | --- | --- |
| PROC-01 | An AWS access key was exposed in a screenshot during the Assignment 5.3 build. It was rotated by the user; the old key now returns `InvalidClientTokenId`. | User-reported from the IAM console: `pantrypulse-dev` has 1 access key, created Oct 8 2026, last used the day of the audit; no older key exists. I cannot verify the old key myself because I do not have it. | Rotated |
| PROC-02 | App #1 (ClauseCompass AI) had the same kind of leak, with a GitHub token. | Recorded as lessons in CLAUDE.md rule 7. | Guarded by SEC-23 below |
| SEC-23 | No secret scanning existed. | gitleaks over all 12 commits and the working tree found nothing; `.env` was never in git history. A pre-commit hook (`.githooks/pre-commit`, installed by `make setup`) blocks `.env` files and runs `gitleaks git --pre-commit --staged`. gitleaks is installed from a pinned, checksum-verified script (`tools/install-gitleaks.sh`). | `test_precommit_hook.py` | Fixed |

## IAM verification (applied by the user)

The first attempts showed the narrowed policy was not the whole story: model listing still worked
twice, first because the console change had not saved, then because `AmazonBedrockReadOnly` was also
attached. After both were removed, with only `pantrypulse-bedrock-invoke-only` attached:

- a real Bedrock call through the app provider succeeded;
- `list-foundation-models`, `list-inference-profiles`, `list-custom-models` and `get-foundation-model`
  returned AccessDeniedException; IAM and S3 calls were also denied.

## Not covered

Production infrastructure (App Runner, RDS, Cognito, S3), TLS termination and WAF are outside this
build. Penetration testing by a third party has not been done.
