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
| S4 | step | Commit and push the code to GitHub over SSH (gitleaks rerun first) | 2026-10-17 13:43:58 | 13:44:17 | 0m19s | gitleaks history+tree clean; committed app changes; pushed main to git@github.com:Khanrazzak18/pantrypulse.git over SSH |
| S5 | step | SSM SecureStrings (JWT secret, DB password, 3 demo passwords) | 2026-10-17 13:44:52 | 13:45:41 | 0m49s | 5 SecureStrings created with generated values (never printed) |
| S6 | fix-up | CloudFormation base stack: ECR, logs 14d, S3, SGs, RDS t4g.micro, IAM roles, OIDC deploy role, bootstrap task def | 2026-10-17 13:45:41 | 13:46:59 | 1m17s | FAILED: Free plan caps RDS backup retention below 7 days (RDS itself is allowed); stack rolled back, nothing left behind |
| F1 | fix-up | Fix-up: RDS backup retention 7 -> 1 day (Free plan maximum); automated backups stay on | 2026-10-17 13:46:59 | 13:54:44 | 7m44s | stack pantrypulse-base CREATE_COMPLETE (RDS available quickly); backups on, 1-day retention; RDS private, only service SG on 5432 |
| S7 | step | Push first image to ECR (ARM64) and run the one-off bootstrap task (2 vCPU / 4 GB) | 2026-10-17 13:54:44 | 14:00:58 | 6m14s | image pushed (first attempt failed: shell treated $R:latest as a lowercase modifier, nothing pushed, wasted task stopped; fixed with braces); bootstrap task 2 vCPU/4 GB: migrate+seed+backtest+forecast+allocation finished in 165 s, exit 0 |
| S8 | step | Create ECS Express service pantrypulse in the default cluster (shared load balancer, ARM64, 0.5 vCPU / 1 GB) | 2026-10-17 14:01:12 | 14:04:04 | 2m51s | service ACTIVE, rollout COMPLETED (~4 min), 1 task running; shares the existing ALB ecs-express-gateway-alb-340ea213 (own target group + host rule); clausecompass untouched. URL https://pa-e3d5d533f4da4f94b6dfd715bea0b319.ecs.us-east-1.on.aws |
| F2 | fix-up | Fix-up: set ALLOWED_ORIGINS to the service URL (known only after the first deploy); logins returned 403 from the Origin check | 2026-10-17 14:04:39 | 14:15:29 | 10m49s | ALLOWED_ORIGINS set via update-express-gateway-service (first try failed: infrastructureRoleArn is not an update parameter); rollout took ~9 min; all 3 logins 200, foreign Origin 403, /api/docs 404 |
| S9 | step | Workflow, aws-bootstrap/aws-down scripts, stack update (ECR EmptyOnDelete), commit, push, first pipeline run | 2026-10-17 14:16:24 | 14:23:07 | 6m42s | pushed bafb2ca; tests/gitleaks/frontend jobs passed in CI; deploy job failed at OIDC role assumption (see F3) |
| F3 | fix-up | Fix-up: GitHub now issues the OIDC subject as repo:OWNER@ID/REPO@ID:ref:refs/heads/main; trust policy updated to that exact subject | 2026-10-17 14:23:15 | 14:23:53 | 0m37s | stack updated; trust policy matches only owner/repo IDs of this repo on refs/heads/main |
