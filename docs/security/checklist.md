# Security checklist

Two parts: **what is in place** (each measure is ticked and names the test, end-to-end row, command or
document that proves it; `backend/tests/test_security_checklist.py` fails if a cited proof does not
exist) and **what to check before every deploy** (settings that differ per environment). The findings
behind these measures, with severity and evidence, are in [`audit.md`](audit.md).

Run everything at once: `make security` (gitleaks, bandit, pip-audit, the npm gate and the security
tests), then `make test` and `make e2e`.

## Measures in place

### Secrets
- [x] `.env` was never committed, is ignored by git, and `.env.example` holds every variable with no real value — proof: `test_env_is_ignored_and_the_example_has_no_real_secret`, `test_the_compose_file_has_no_password_in_it`
- [x] Secret scanning over the whole git history and the working tree finds nothing — proof: `make security`, `.gitleaks.toml`
- [x] A pre-commit hook blocks `.env` files, AWS keys and private keys before they are committed — proof: `test_an_aws_key_in_a_file_blocks_the_commit`, `test_a_private_key_blocks_the_commit`, `test_environment_files_are_blocked_even_with_harmless_content`
- [x] The hook is installed by setup and is executable in the real repository — proof: `test_the_real_repository_has_the_hook_and_it_is_executable`, `make hooks`
- [x] The app refuses to start without a strong JWT secret (32+ characters) — proof: `test_app_refuses_to_start_without_a_strong_jwt_secret`
- [x] No built-in demo passwords exist in code; `make seed` reads them from `.env` — proof: `test_settings_has_no_built_in_demo_passwords`, `test_missing_demo_passwords_fail_with_a_clear_message`
- [x] The public demo passwords are refused when the site is served over https — proof: `test_the_public_demo_passwords_are_refused_on_an_https_site`
- [x] No database URL or password is logged or printed — proof: `test_no_database_url_or_password_is_logged_or_printed`
- [x] AWS access comes from a CLI profile, never keys in `.env`; the AWS key exposed in a screenshot during the 5.3 build was rotated (one key remains, created 2026-10-08, reported from the IAM console) — proof: `docs/security/audit.md`

### AWS IAM
- [x] The AWS user may only call `bedrock:InvokeModel` on the Claude Haiku 4.5 inference profile and its foundation models — proof: `test_the_policy_allows_exactly_one_action_and_nothing_with_a_wildcard_action`, `test_the_resources_are_only_the_haiku_inference_profile_and_its_foundation_models`, `docs/security/iam-policy.json`
- [x] The configured model is the one the policy allows — proof: `test_the_model_the_app_is_configured_for_is_the_one_the_policy_allows`
- [x] The app calls no Bedrock API other than Converse, so no discovery permission is needed — proof: `test_the_app_calls_no_bedrock_api_other_than_converse`
- [x] Verified live after the policy was applied: a real model call works and listing, describing and custom-model calls are denied (it took three attempts: a second managed policy was still attached) — proof: `docs/security/audit.md`

### Authentication and sessions
- [x] Passwords are stored as argon2 hashes and never returned — proof: `test_demo_passwords_are_stored_hashed_and_verify`, `test_login_response_never_contains_the_token_or_the_password_hash`
- [x] The session is a signed token in an httpOnly, SameSite=Lax cookie, Secure over https — proof: `test_login_sets_an_httponly_lax_cookie_and_returns_the_user`, `test_cookie_is_marked_secure_when_configured`
- [x] Tokens expire, and tampered or garbage tokens are refused — proof: `test_token_lifetime_matches_the_requested_hours`, `test_a_tampered_payload_is_rejected`, `test_an_expired_token_returns_401`, `test_a_garbage_cookie_returns_401`
- [x] Logout revokes every session of that user, even a copied cookie — proof: `test_logout_revokes_the_token_even_if_it_was_copied`, `test_logout_ends_every_session_of_that_user_but_nobody_elses`, `SEC-06`, `SEC-07`
- [x] Changing a user's role, pantry, password or active flag revokes their sessions — proof: `test_changing_a_user_through_the_app_bumps_the_version`, `test_a_user_deactivated_after_login_is_locked_out_immediately`
- [x] Unknown email and wrong password give the same answer, and an unknown email still costs a password check — proof: `test_unknown_email_gets_exactly_the_same_response_as_a_wrong_password`, `test_a_password_is_checked_even_for_an_unknown_email`
- [x] Five failures per email or 20 per address lock login for 15 minutes, counted in the database and stored as hashes — proof: `test_the_fifth_failure_locks_even_for_the_right_password`, `test_one_address_trying_many_emails_gets_locked`, `test_the_table_stores_hashes_not_emails`
- [x] `X-Forwarded-For` is believed only from proxies in `TRUSTED_PROXIES`, so a forged header cannot dodge the address limit — proof: `test_forging_the_header_does_not_dodge_the_per_address_limit`, `test_a_header_from_an_unlisted_peer_is_ignored`
- [x] Logged-out visitors are redirected from every protected page, `/admin` included — proof: `SEC-08`, `ANON-04`

### Authorization
- [x] Every route is in an access table and each role gets exactly the access it should (401 logged out, 403 wrong role) — proof: `test_every_route_is_in_the_access_table`, `test_each_role_gets_exactly_the_access_it_should`, `make security`
- [x] A pantry manager reaches only their own pantry's data — proof: `test_a_manager_reaches_only_their_own_pantry`
- [x] Slow AI routes are closed to the wrong roles before any work starts — proof: `test_slow_routes_are_closed_to_the_wrong_roles_too`
- [x] Every route refuses a logged-out caller or the wrong role in the error envelope — proof: `test_every_route_refuses_a_logged_out_caller_in_the_envelope`, `test_every_route_refuses_the_wrong_role_in_the_envelope`
- [x] The API documentation is not public by default — proof: `test_the_api_documentation_is_not_public_by_default`

### Input validation
- [x] Every id, date, month and text field uses a shared validated type (ids fit the database, dates 2020 to 2100, no control characters) — proof: `test_ids_must_fit_the_database`, `test_dates_must_be_between_2020_and_2100`, `test_control_characters_are_rejected_everywhere`
- [x] Bad bodies and filters on every form route are refused with a 422 in the error envelope — proof: `test_login_rejects_bad_bodies`, `test_allocation_edit_rejects_bad_bodies`, `test_dashboard_range_rejects_bad_dates`, `test_summary_text_over_the_limit_is_refused_and_nothing_is_saved`
- [x] Hostile input to every route as three callers never produces a server error — proof: `test_fuzz_logged_out`, `test_fuzz_as_a_pantry_manager`, `test_fuzz_as_an_admin`, `test_the_fuzzer_covers_a_lot_of_ground`
- [x] The database enforces the rules too: foreign keys, NOT NULL, CHECK constraints — proof: `test_database_rejects_bad_data`, `test_valid_rows_in_every_table_are_accepted`
- [x] The request body is counted as it streams in: 413 at 1 MB of JSON or 11 MiB of upload, chunked or lying about its length — proof: `test_a_chunked_json_body_over_the_limit_is_refused_without_a_content_length`, `test_a_request_that_lies_about_a_small_length_is_stopped_when_it_exceeds_the_limit`
- [x] Every error uses one envelope with a request id, and a database outage is a 503, not a 500 — proof: `test_unknown_routes_and_methods_use_the_envelope`, `test_health_returns_error_envelope_when_database_is_down`

### SQL injection
- [x] Every raw SQL statement is a constant string, none is built from request data, and the reviewed inventory is pinned — proof: `test_every_raw_sql_text_is_a_constant_string`, `test_no_sql_is_built_with_f_strings_formats_or_concatenation`, `test_the_inventory_of_raw_sql_is_the_one_that_was_reviewed`
- [x] Values reach raw SQL only as bound parameters; the seed script quotes table names — proof: `test_values_reach_raw_sql_only_as_bound_parameters`, `test_the_seed_script_quotes_every_table_name_it_puts_in_sql`
- [x] Injection payloads (including a sleep) through every route change no rows and delay nothing — proof: `test_fuzz_logged_out`, `make security`
- [x] bandit finds no issue in the application code — proof: `make security`

### XSS and CSP
- [x] The front end never uses an HTML injection API; AI text is shown as text — proof: `test_the_front_end_never_uses_an_html_injection_api`, `SEC-05`
- [x] A per-request nonce CSP with no `'unsafe-inline'` for scripts, plus frame blocking, nosniff, Referrer-Policy and Permissions-Policy on every page — proof: `SEC-01`, `SEC-02`
- [x] An inline script or event handler added without the nonce does not run (checked in Chromium and WebKit) — proof: `SEC-03`
- [x] The API sends its own restrictive headers on every response, errors included, and is never cached — proof: `test_every_api_response_has_the_security_headers`, `test_headers_are_on_error_responses_too`, `test_api_responses_are_never_cached`
- [x] HSTS is sent only when the site is served over https — proof: `test_hsts_is_sent_only_when_the_site_is_served_over_https`

### CSRF
- [x] A state-changing request from another origin, or with cross-site fetch metadata, is refused before anything changes — proof: `test_a_post_from_another_site_is_refused`, `test_the_refusal_happens_before_anything_is_changed`, `test_a_lookalike_origin_is_refused`, `SEC-09`
- [x] Every method that changes data is checked, login included; the app's own requests and non-browser clients still work — proof: `test_every_method_that_changes_data_is_checked`, `test_login_is_protected_too`, `test_our_own_site_is_allowed`, `test_requests_without_browser_headers_are_allowed`

### Uploads
- [x] Only pdf, png, jpg, webp, txt and eml are accepted, and the file's content must match its extension — proof: `test_wrong_file_types_get_a_readable_415`, `test_files_that_are_not_what_their_extension_says_are_rejected`
- [x] 10 MB maximum, empty files refused, nothing left behind if storing fails — proof: `test_a_file_over_10_mb_is_rejected_with_a_readable_413`, `test_an_empty_file_is_rejected`, `test_if_storing_the_file_fails_nothing_is_left_behind`
- [x] Stored under a random name, never the uploaded one, outside every served folder; no route returns a stored file — proof: `test_stored_files_get_random_names_never_the_uploaded_name`, `test_uploaded_files_are_kept_outside_every_folder_that_is_served`, `test_no_route_hands_back_a_stored_file`, `test_uploaded_filenames_never_become_storage_paths`
- [x] Files go through a storage interface that rejects unsafe keys — proof: `test_unsafe_keys_are_rejected_for_every_operation`
- [x] Hostile upload names and contents never cause a server error — proof: `test_fuzz_upload_file_names`, `test_fuzz_upload_file_contents`

### Rate limits and cost
- [x] Per-user hourly limits on uploads (20), each AI endpoint (30) and the weekly refresh (6), configurable and counted in the database — proof: `test_the_defaults_are_the_documented_ones`, `test_each_limit_triggers_after_its_configured_number_of_requests`, `test_the_counter_lives_in_the_database_so_every_instance_shares_it`
- [x] Limits are per user and per endpoint, the window resets, and the role check runs before counting — proof: `test_limits_are_per_user`, `test_limits_are_per_endpoint`, `test_the_window_resets_after_an_hour`, `test_a_logged_out_caller_is_refused_before_anything_is_counted`
- [x] Every model call has an output-token cap and a time limit, enforced inside the provider — proof: `test_every_call_has_a_token_cap`, `test_every_call_has_a_time_limit`, `test_every_app_call_site_passes_a_token_cap_and_a_timeout_within_the_limits`

### Logging and privacy
- [x] Logs are structured JSON with a request id and contain no credentials or tokens — proof: `test_request_log_line_is_json_with_required_fields`, `test_login_logout_and_failures_never_log_credentials_or_tokens`
- [x] Uploaded manifest text, notes and summaries are never logged — proof: `test_an_uploaded_manifests_text_is_never_logged`, `test_notes_and_summaries_are_not_logged`, `test_logs_contain_the_outcome_but_not_the_manifest`
- [x] A database error never puts row values in the log, and an unexpected error shows the client neither type nor trace — proof: `test_a_database_error_does_not_put_the_values_in_the_log`, `test_an_unexpected_error_logs_the_type_and_trace_but_the_client_gets_neither`, `test_the_engine_hides_parameters`
- [x] Counters store hashes, not emails or user ids — proof: `test_the_table_stores_hashes_not_user_ids`
- [x] Postgres is published on `127.0.0.1` only — proof: `test_postgres_is_published_on_the_loopback_address_only`
- [x] Data minimisation: the model gets the manifest or aggregate totals, never users, households or logins — proof: `docs/responsible-ai.md`, `test_the_manifest_is_sent_as_data_next_to_a_system_prompt_that_says_so`

### LLM and prompt injection
- [x] A hostile manifest creates one donation waiting for review and changes no other record — proof: `test_a_prompt_injection_in_a_manifest_creates_only_one_donation_waiting_for_review`, `test_model_output_never_reaches_inventory_without_confirmation`
- [x] The manifest is untrusted data in the user turn, never in the system prompt — proof: `test_the_manifest_is_sent_as_data_next_to_a_system_prompt_that_says_so`
- [x] The model has one forced data-return tool per call, no tool that writes, and a call to any other tool is ignored — proof: `test_the_provider_offers_exactly_one_tool_and_forces_the_model_to_use_it`, `test_the_only_tools_the_app_ever_offers_are_the_three_forced_output_tools`, `test_a_tool_call_for_any_other_name_is_ignored`
- [x] Output is validated against a schema, retried once, then reported as an error; hostile output is stored as inert text — proof: `test_an_answer_that_breaks_the_schema_counts_as_invalid`, `test_invalid_output_twice_fails_clearly_and_saves_nothing`, `test_hostile_model_output_is_validated_or_stored_as_inert_text`
- [x] Invented numbers in reasons and summaries are refused — proof: `test_a_number_that_is_not_in_the_aggregates_is_refused`, `test_ai_reason_with_an_invented_number_keeps_the_template`
- [x] Hostile AI text is shown as text and runs nothing in the browser — proof: `SEC-05`
- [x] A live check against the real model with three injection manifests produced only the legitimate items — proof: `docs/security/injection-check.md`, `backend/eval/injection_check.py`
- [x] Humans approve every donation, allocation and monthly summary — proof: `test_nothing_enters_inventory_until_the_coordinator_confirms`, `docs/responsible-ai.md`

### Dependencies
- [x] pip-audit reports no known vulnerability, and npm audit reports none in production dependencies — proof: `make security`
- [x] The npm gate fails on any high or critical advisory other than the one accepted, and fails on that one if it reaches production — proof: `test_an_accepted_dev_advisory_passes_but_any_production_one_fails`, `test_a_high_advisory_is_found_and_names_in_the_chain_are_ignored`
- [x] Every accepted exception has a written reason — proof: `test_the_accepted_risks_file_explains_each_exception`, `docs/security/accepted-risks.json`
- [x] The security scanner is installed from a pinned, checksum-verified script — proof: `tools/install-gitleaks.sh`, `make security-tools`

### Data retention
- [x] Raw model output is cleared 90 days after review (configurable), pending donations never; the marker records when — proof: `test_output_reviewed_more_than_90_days_ago_is_cleared`, `test_recent_and_unreviewed_output_is_kept`, `test_the_boundary_is_exactly_ninety_days`
- [x] The database refuses a cleared marker on output that still exists or on a pending donation — proof: `test_the_database_refuses_a_cleared_marker_on_a_donation_that_still_has_output`, `test_the_database_refuses_clearing_a_pending_donation`
- [x] The weekly refresh runs the clearing and reports how many; a cleared donation still opens and says so — proof: `test_the_weekly_refresh_clears_old_output_and_reports_how_many`, `test_a_cleared_donation_still_opens_and_says_its_output_was_cleared`
- [x] The retention period and the reason for keeping the output are documented — proof: `test_the_retention_period_is_documented`, `docs/security/audit.md`

## Accepted risks

Two risks are accepted on purpose; everything else in `audit.md` is fixed or verified. Both are recorded with
a reason in `docs/security/accepted-risks.json` and `audit.md`.

1. **`style-src 'unsafe-inline'` in the Content-Security-Policy (SEC-14).** Next.js and Recharts write inline `style`
   attributes, which a nonce cannot cover, so removing it breaks the layout and the charts. Scripts, where code execution
   risk is, use a nonce with `strict-dynamic` and no `'unsafe-inline'`, and `SEC-03` proves an unnonced inline script
   and handler do not run. What remains is that someone who could already inject markup could restyle the page, not run code.
   *Revisit:* when Next.js or Recharts support nonce or hash styles; at every major upgrade of either; and before the app holds data more sensitive than pantry operations.
2. **`braces` advisory GHSA-vfj7-8cjw-p6xm, npm, dev only (SEC-17).** Five high findings come from one chain
   (`eslint-config-next`, via `braces` 3.0.3 or older). No patched release exists, and the only forced fix downgrades
   `eslint-config-next` to a version incompatible with Next.js 16. `npm audit --omit=dev` reports zero, so none of it ships.
   `make security` fails on any other high or critical advisory, and on this one if it reaches production.
   *Revisit:* when a patched `braces` or `eslint-config-next` is published; at every release; and when CI changes.

## Before every deploy

Settings that differ per environment and cannot be proved by a test in this repository.

- [ ] `make security` passes (gitleaks history and tree, bandit, pip-audit, npm audit gate, role-by-route and fuzz tests).
- [ ] `make test` and `make e2e` pass.
- [ ] `.env` is not tracked (`git ls-files .env` is empty); the pre-commit hook is active (`git config core.hooksPath` is `.githooks`).
- [ ] `JWT_SECRET` is at least 32 random characters and differs per environment.
- [ ] `COOKIE_SECURE=true`; the site is served over https; `make seed` is not run with public demo passwords.
- [ ] `EXPOSE_API_DOCS` is unset or false.
- [ ] `ALLOWED_ORIGINS` lists only the real web origin (if set).
- [ ] The AWS identity can only `bedrock:InvokeModel` on the model in `docs/security/iam-policy.json`: a listing call is denied.
- [ ] Only one access key exists per IAM user, and no key is older than 90 days.
- [ ] Postgres is not reachable from outside the host or VPC.
- [ ] `TRUSTED_PROXIES` lists the real proxy (not empty behind a load balancer), uvicorn runs with `--no-proxy-headers`, and the proxy enforces its own request-size limit and timeouts.
- [ ] `RAW_OUTPUT_RETENTION_DAYS` matches the food bank's policy and the weekly refresh runs (it clears reviewed raw model output).
- [ ] Rate limits in `.env` match the expected team size.
- [ ] Any new route has an entry in the `ACCESS` table of `test_authorization_matrix.py`.
- [ ] Any new raw SQL statement is parameterised and added to the inventory in `test_sql_hygiene.py`.
- [ ] Any new model call passes a token cap and a timeout and uses a forced tool that only returns data.
- [ ] `docs/security/accepted-risks.json` is reviewed; each item still has no patched release.

## Production on AWS (verified on the live site, 2026-10-17 and 2026-10-18)

Facts about the deployed environment that no test in this repository can prove. Evidence is in `docs/deploy/deploy-log.md`.

- [x] HTTPS only, with `Strict-Transport-Security`, the CSP (per-request nonce), `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` and the cross-origin headers on the live URL (checked with `curl -I`).
- [x] `COOKIE_SECURE=true`; a foreign `Origin` on a login gets 403 and the site's own origin gets 200; `/api/docs` is 404.
- [x] All three logins work with strong, generated passwords stored as SSM SecureStrings (`/pantrypulse/*`); the public example passwords are not used and the app refuses them when `COOKIE_SECURE=true`.
- [x] The database is not publicly accessible; its security group allows port 5432 only from the service security group; storage is encrypted; automated backups are on (1-day retention, the Free plan maximum).
- [x] The uploads bucket blocks all public access, is encrypted (AES-256) and refuses non-TLS requests.
- [x] The task role can only `bedrock:InvokeModel` on Claude Haiku 4.5 plus read, write and delete on the uploads bucket; real intake of an email and a PDF worked with it.
- [x] No AWS keys anywhere: the service uses its task role; GitHub Actions uses OIDC; the deploy role trusts only this repository's `main` branch (by owner and repository ID) and can only push the one ECR repository, update the one service, run the bootstrap task and pass three roles.
- [x] `TRUSTED_PROXIES` is loopback plus the VPC range `172.31.0.0/16`; uvicorn runs with `--no-proxy-headers`.
- [x] The service log group has 14-day retention; no error or warning lines in the service log during verification.
- [ ] Accepted for the demo: the shared load balancer's security group also allows port 80 (it is the other app's load balancer and was not modified, and what it does with plain HTTP was not tested; the app's own HSTS applies once a browser has used HTTPS); backups keep one day; one database in one zone.

