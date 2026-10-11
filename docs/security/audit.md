# PantryPulse security audit (Stage 12)

Scope: the whole repository, git history, the running API and web app, the AWS account permissions of
`pantrypulse-dev`, and the Bedrock call paths. Method: gitleaks (history and tree), bandit, pip-audit,
npm audit, a manual review of every raw SQL statement, automated role-by-route and fuzz tests, header
and CSP checks in a real browser, and one live prompt-injection run against the real model.

OWASP categories are from the Top 10 (2021) and the Top 10 for LLM Applications (LLM01..LLM10, 2025).
"Test" names the automated test that now fails if the fix is removed.

## Summary

| Severity | Found | Fixed or verified | Accepted | Open |
| --- | --- | --- | --- | --- |
| High | 4 | 4 | 0 | 0 |
| Medium | 10 | 8 | 2 (SEC-14, SEC-17) | 0 |
| Low | 8 | 8 | 0 | 0 |
| Process | 3 | 3 | 0 | 0 |

There are no open findings. Two risks are accepted on purpose (see "Accepted risks" below); everything
else is fixed or verified by an automated test. Stage 13a closed SEC-15, SEC-16 and SEC-20.

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
| SEC-09 | A04 Insecure Design | Medium | `security/http.py` | Request bodies were read before size checks, so a huge body was buffered. | 413 `payload_too_large` from the declared `Content-Length` (1 MB for JSON, 11 MiB for uploads) before the body is read. The 10 MB file check remains. | `test_data_handling.py` | Fixed (declared size; streamed size is SEC-16) |
| SEC-10 | A09 Security Logging and Monitoring Failures | Medium | `db.py`, `logging.py` | A database error message could quote row values (for example "Key (email)=(...)") into logs. | `hide_parameters=True` on the engine and a log formatter that removes DETAIL, CONTEXT, HINT and parameter lines. | `test_log_hygiene.py` | Fixed |
| SEC-11 | A03 Injection (SQL) | Low | 20 `text()` calls | Every raw statement reviewed: all are constant strings except `scripts/seed.py` (table names built with f-strings from a fixed list) and `scripts/e2e_server.py` / `eval` (not on the request path). Bandit B608 flagged `seed.py`. | `seed.py` quotes identifiers through one `quote()` helper. All request-path code uses the ORM or bound parameters. An inventory test fails if a new raw statement appears. Injection payloads were added to the fuzz test, with a `pg_sleep` payload that must not delay a response, and row counts that must not change. | `test_sql_hygiene.py`, `test_api_fuzz.py` (49 cases), bandit | Fixed |
| SEC-12 | A02 Cryptographic Failures / A07 | Low | `scripts/seed.py` | The documented demo passwords are public. | `make seed` refuses them when `COOKIE_SECURE=true`. Demo passwords are in the README as local-only. | `test_seed.py` | Fixed |
| SEC-13 | A05 / least privilege (A01) | Medium | AWS user `pantrypulse-dev` | The user had `AmazonBedrockFullAccess`, later also `AmazonBedrockReadOnly` (found during verification). README's example policy included discovery actions. | Policy in `docs/security/iam-policy.json`: `bedrock:InvokeModel` only, on the Haiku 4.5 inference profile and its foundation models. Applied in the console (see evidence below). The README policy no longer has discovery actions. | `test_iam_policy.py` (policy pinned to the code) and a live check | Fixed |
| SEC-14 | A05 Security Misconfiguration | Medium | CSP `style-src` | **`style-src` still contains `'unsafe-inline'`.** Next.js and Recharts write inline `style` attributes, which a nonce cannot cover. Scripts do not use `'unsafe-inline'` (nonce plus `strict-dynamic`; `'unsafe-eval'` only in `next dev`). | Accepted. Style injection can restyle or exfiltrate through CSS but cannot run code; script execution is blocked by the policy. | E2E SEC-01 checks the policy on every page with no violations | Accepted risk (see below) |
| SEC-15 | A04 Insecure Design | Low | login lockout | The per-address login limit read `X-Forwarded-For` from anyone, so a caller could forge the address. | `X-Forwarded-For` is believed only when the direct peer is in `TRUSTED_PROXIES` (empty by default); the right-most entry that is not a trusted proxy is used, so a forged prefix is never reached. uvicorn runs with `--no-proxy-headers` so this is the only place the header is trusted. Production must list its real proxy (documented in `.env.example` and the README). | `test_trusted_proxies.py` (unit cases, a forged header cannot dodge the limit, a trusted proxy gives each caller their own limit) | Fixed (Stage 13a) |
| SEC-16 | A04 Insecure Design | Low | uploads and JSON bodies | A request with no `Content-Length` (chunked) or a false one was bounded only by the framework. | `BodyLimit` ASGI middleware counts bytes as they arrive and, at the limit (1 MB JSON, 11 MiB upload request), sends the 413 envelope and stops the read; the declared-length refusal stays as the fast path. | `test_body_stream_limit.py` (chunked JSON, chunked upload, a request that claims 10 bytes then sends more) | Fixed (Stage 13a) |
| SEC-17 | A06 Vulnerable and Outdated Components | Medium | `frontend` dev dependencies | `npm audit` reports 5 high in the `eslint-config-next` chain (`braces` <=3.0.3, GHSA-vfj7-8cjw-p6xm). No patched release exists; the only `--force` fix downgrades `eslint-config-next` to 14. `npm audit --omit=dev` reports 0 vulnerabilities. | Recorded in `docs/security/accepted-risks.json`; `make security` fails on any other high or critical advisory. pip-audit: no known vulnerabilities. | `test_audit_gate.py` | Accepted (see below) |
| SEC-18 | LLM01 Prompt Injection | Medium | intake, reasons, summaries | Manifests are untrusted text that reaches the model. | The text goes in the user turn inside `<manifest>` tags (a closing tag in the text is neutralised) and the system prompt says it is data. The model gets exactly one tool and is forced to call it; the tool only returns a list that is validated by Pydantic; a call to any other tool name is ignored. Nothing is written until a coordinator confirms. Live run against the real model with three injection manifests: all three produced only the legitimate item, no extra fields (`docs/security/injection-check.md`). | `test_llm_safety.py` (15 tests), `eval/injection_check.py` | Fixed |
| SEC-19 | LLM05 Improper Output Handling | Low | frontend | Model text is rendered in the UI. | React escapes text; there is no `dangerouslySetInnerHTML`. A hostile donor name, item name and notes render as text and no script runs. | E2E SEC-05, `test_llm_safety.py` | Fixed |
| SEC-20 | LLM02 Sensitive Information Disclosure | Low | `donations.raw_llm_output` | The raw model output was kept forever. It is audit evidence of what the model said versus what a coordinator confirmed, and it can quote donor text. Bedrock receives only the manifest and today's date (checked in `build_content`). | Kept for audit, then cleared **90 days** after review (confirmed or rejected; configurable with `RAW_OUTPUT_RETENTION_DAYS`) by the weekly refresh. `raw_output_cleared_at` records when; a check constraint allows the marker only on a reviewed donation whose output is gone. Pending donations are never cleared. Model id, latency, token counts, confirmed items and edit logs stay. The detail page says when the output was cleared. | `test_raw_output_retention.py` (91 vs 89 days, pending kept, boundary, constraints, refresh job, detail view) | Fixed (Stage 13a) |
| SEC-21 | A03 Injection (XSS), A08 Software and Data Integrity | Low | uploads | Files must be pdf, png, jpg, webp, txt, eml and at most 10 MB; the stored name is generated, the file type is checked against magic bytes (intake tests); no route serves stored files. | Verified by test; no change needed beyond SEC-09. | `test_data_handling.py` | Verified |
| SEC-22 | A02 Cryptographic Failures | Low | Postgres | Database port exposure. | Compose publishes Postgres on `127.0.0.1` only (checked by test). | `test_data_handling.py` | Verified |

## Accepted risks

Two risks stay accepted. Each has a reason and a point at which it is looked at again.

**SEC-14: `style-src 'unsafe-inline'` in the CSP.**
- *Why it stays:* Next.js and Recharts write inline `style` attributes. A nonce or hash cannot cover a style attribute, so removing `'unsafe-inline'` from `style-src` breaks the charts and layout. Scripts, where the real code-execution risk is, use a per-request nonce with `strict-dynamic` and no `'unsafe-inline'`; the E2E test SEC-03 proves an unnonced inline script and an inline `onerror` handler do not run.
- *What the risk is:* an attacker who could already inject markup could restyle the page or leak data through CSS. They could not run code.
- *Revisit:* when a Next.js or Recharts release supports nonce or hash styles (`style-src-attr` / `'unsafe-hashes'`); at every major upgrade of either; and before any deployment that handles more sensitive data than pantry operations.

**SEC-17: `braces` advisory GHSA-vfj7-8cjw-p6xm (npm, dev only).**
- *Why it stays:* five high findings come from one dev-only chain (`eslint-config-next`, via `braces` <= 3.0.3). No patched release exists, and the only `npm audit fix --force` path downgrades `eslint-config-next` to 14, which is incompatible with Next.js 16. `npm audit --omit=dev` reports 0 vulnerabilities, so none of it ships.
- *Control:* recorded in `docs/security/accepted-risks.json`; `make security` fails on any other high or critical advisory, and on this one if it ever reaches production dependencies.
- *Revisit:* when a patched `braces` or `eslint-config-next` is published; at every release; and on any change to what runs in CI.

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
