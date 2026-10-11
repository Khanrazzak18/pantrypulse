# Security checklist (run before every deploy)

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
