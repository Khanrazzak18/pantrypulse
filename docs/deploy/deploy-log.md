# Deployment log: PantryPulse on AWS (Stage 16)

Every step and every fix-up with its real start and end time (America/New_York), written as it happened.
Comparable with the first deployment (the first app, on AWS Amplify, which this stage did not touch).

- **Start of Stage 16: 2026-10-16 17:40:50** (the time of the approval message).
- Region us-east-1, default VPC. Target: Amazon ECS Express Mode (AWS App Runner is closed to new customers since 2026-04-30).
- AWS profile: `default` (the Workshop 3 profile). Verified first: account <ACCOUNT_ID>, principal `user/cli-admin`, not root.
- The GitHub repository `Khanrazzak18/pantrypulse` was **created in the browser by the owner**, so no token, `gh` install or
  CLI login was needed; the code is pushed over SSH.

| Step | Kind | What | Date and start | End | Duration | Result |
| --- | --- | --- | --- | --- | --- | --- |
| S0 | step | Preflight: identity and account plan | 2026-10-16 17:41:29 | 17:41:29 | 0m00s | default profile = account <ACCOUNT_ID>, user/cli-admin (not root) |
| S1 | step | Pre-push checks: gitleaks (history + tree), .env ignored, account-id placeholder, .env.example note | 2026-10-16 17:41:43 | 17:41:56 | 0m13s | history (16 commits) and tree: no leaks; .env ignored and never committed; account id replaced by <ACCOUNT_ID> in current docs (history unchanged, as agreed); .env.example says demo passwords are local-only |

## Status check, 2026-10-17 (account <ACCOUNT_ID>, profile `default`)

- **Finding: the second app (PantryPulse) is not deployed.** Stage 16 stopped at S2 (app code changes: S3Storage, config, bootstrap). No ECR repo,
  RDS, S3 bucket, Express service or GitHub push exists yet, so there is no live URL. The only ECS service is `clausecompass` (first app).
- First app on Amplify (`dbijq8i6xjphl`, branch `main`): job 3 completed, https://main.dbijq8i6xjphl.amplifyapp.com returns 200.
- First app on ECS Express (`clausecompass`, 0.5 vCPU/1 GB, x86): ACTIVE, 1 task, `/api/health` ok, steady state, logs clean.
- No EC2 instances, RDS, NAT gateways or unattached volumes. 6 public IPv4 addresses belong to the shared Express ALB.
- Cost, last 7 days (before credits): VPC (public IPv4) $6.09, ECS $4.30, Load Balancing $3.92, Bedrock Haiku $0.19 = **$14.50 (about $2.07/day)**,
  covered by credits. Remaining credits: **$104.33** (Free plan until 2027-03-16).
- Created: budget `portfolio-apps-monthly-40` ($40/month, email at 80% actual and 100% forecast); dashboard `portfolio-apps` (App #1 Amplify requests
  and 5xx; App #2 widgets to be added after deploy). Nothing deleted. Existing budget `Monthly-5-USD` left as is.
| S2a | step | App changes part 1: S3Storage, config, tests for both, bootstrap tests written | 2026-10-16 17:42:09 | 17:53:59 | 11m50s | S3Storage with SSE, make_storage, sslmode/storage settings, 50 tests passing; bootstrap tests written (fail until implemented) |
| GAP | gap | **Stall: session ran out of context and work paused. Not deployment time.** | 2026-10-16 17:53:59 | 2026-10-17 13:37 | 19h43m | Excluded from all durations. Work resumed at 13:37. |
| S2b | step | App changes part 2: bootstrap script (after the gap) | 2026-10-17 13:37:22 | 13:40:00 | 2m38s | bootstrap.py (advisory lock, idempotent per-step probes, migrate-only mode); 12 bootstrap tests, full backend suite 1219 passed, ruff clean. Docker Desktop had to be started |
| S3 | step | Dockerfile, entrypoint with clean shutdown, local ARM64 build and smoke test | 2026-10-17 13:40:00 | 13:43:52 | 3m51s | Dockerfile (node build stage + python slim, tini, non-root), entrypoint migrates then runs both servers; ARM64 build 1m13s, all wheels available (no x86 fallback); /api/health ok; stop = 0.4s exit 0; real bootstrap in container (2 CPU/4 GB) 77s, peak 390 MB, rerun is a no-op |
