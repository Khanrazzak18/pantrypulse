# PantryPulse

AI food allocation for Harvest Bridge Food Bank, a hypothetical regional non-profit. See
`docs/spec-5.2.md` for the use case, `CLAUDE.md` for the build contract and `docs/architecture.md`
for design decisions.

**Status:** Stage 4 of 9 (AI donation intake). The full README (features, AI evaluation results, known
limitations) is written in Stage 8.

## Requirements

Docker, Node 20+, Python 3.12+, make, and (for AI intake) an AWS account with Bedrock access.

## Quick start

```bash
cp .env.example .env     # then fill in POSTGRES_PASSWORD and JWT_SECRET (the DEMO_* lines can stay as they are)
make setup               # backend/.venv + frontend dependencies
make db                  # Postgres 16 in Docker (creates pantrypulse and pantrypulse_test)
make migrate             # create the tables
make seed                # synthetic history + demo users
make dev                 # API on :8000, web on :3000 (Ctrl-C stops both)
```

Check it works: `curl localhost:3000/api/health` returns `{"status":"ok","database":"ok"}`.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | Install backend and frontend dependencies |
| `make db` | Start Postgres in Docker |
| `make migrate` | Apply Alembic migrations to the app database |
| `make seed` | Reload the synthetic history and demo users (destructive for the app database) |
| `make dev` | API and web together |
| `make api-types` | Regenerate the frontend's typed API client after changing the API |
| `make test` | ruff + pytest, then frontend lint, typecheck and build (needs `make db`) |
| `make eval` | Score the AI intake against the 50 golden manifests (calls Bedrock) and write `docs/eval/intake-eval.md`; the forecast backtest joins it in Stage 5 |
| `make golden` | Rebuild the golden manifests from their fixed seed |
| `make refresh` | Weekly retrain and allocation job (Stage 6) |

Ports are set only in `.env`. Secrets never go in git; AWS access uses the CLI profile in
`AWS_PROFILE`, not access keys.

## AI donation intake and Bedrock setup

Coordinators and admins upload an email, PDF or photo of a donation manifest at
**Donations**. Amazon Bedrock reads it, and you review and edit the items (fields the AI was
unsure about, under 80% confidence, are highlighted) before **Confirm** turns them into
inventory lots. **Reject** adds nothing.

1. Credentials come from an AWS CLI profile, never from `.env` keys:
   `aws configure --profile pantrypulse`, then set `AWS_PROFILE=pantrypulse` and
   `AWS_REGION=us-east-1` in `.env`.
2. Set `BEDROCK_MODEL_ID` in `.env` to an inference profile ID (it starts with `us.`). The default
   in `.env.example` is `us.anthropic.claude-haiku-4-5-20251001-v1:0`. (Claude Haiku 5.5 was listed
   but not available to this account, so Haiku 4.5 is used.)
3. The first time an account uses an Anthropic model, open it once in the Bedrock console
   playground and submit the one-time use-case form.
4. Give the AWS user permission to call the model. **Minimum IAM policy** (replace
   `<ACCOUNT_ID>`); `bedrock:InvokeModel` is the permission the Converse API checks. A `us.`
   inference profile can route to several US regions, so the foundation-model ARN uses `*` for
   the region:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeTheIntakeModel",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1:<ACCOUNT_ID>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    },
    {
      "Sid": "OptionalModelDiscovery",
      "Effect": "Allow",
      "Action": ["bedrock:ListInferenceProfiles", "bedrock:GetInferenceProfile", "bedrock:ListFoundationModels"],
      "Resource": "*"
    }
  ]
}
```

The second statement is only for finding model IDs and can be left out. Switching models means
changing both the model ID in `.env` and the resources above. `AmazonBedrockFullAccess` also
works but grants far more than the app needs.

Tests never call Bedrock (they use a scripted fake, and a guard fails any test that tries to
create an AWS client). Only the running app and `make eval` use the real service.

### AI evaluation results

`make eval` scores the model on 50 synthetic manifests (30 emails, 15 PDFs, 5 photos). Latest run
with `us.anthropic.claude-haiku-4-5-20251001-v1:0`: **98.7% field-level accuracy** (target 95%),
all 287 items found, 224,218 tokens in total. The first scoring of the same answers was 92.9%
because the answer key accepted only one name per food; see the scoring note and the list of
remaining mistakes in [docs/eval/intake-eval.md](docs/eval/intake-eval.md). The set is synthetic
and the key was corrected after seeing the first result, so treat the number as a regression
check, not a blind measurement of real manifests.

## Demo logins (local only)

`make seed` creates these users. The passwords are the `DEMO_*` values in `.env`; the defaults in
`.env.example` are below. They are demo credentials for local development, not real secrets.
Log in at http://localhost:3000/login.

| Role | Email | Password variable | Default |
| --- | --- | --- | --- |
| Coordinator | `coordinator@harvestbridge.example.org` | `DEMO_COORDINATOR_PASSWORD` | `demo-coordinator-pw` |
| Admin | `admin@harvestbridge.example.org` | `DEMO_ADMIN_PASSWORD` | `demo-admin-pw` |
| Pantry manager (Pantry 14) | `manager14@harvestbridge.example.org` | `DEMO_PANTRY_MANAGER_PASSWORD` | `demo-manager-pw` |

`make seed` fails with a clear message if any of these variables is missing from `.env`.

## About the data

All data is synthetic. Harvest Bridge Food Bank is hypothetical, the six counties are fictional,
and **the weather, school holidays and benefit-payment weeks are generated, not real**. The
generator uses a fixed seed, so the same data comes out every time. See
`docs/architecture.md` for how it works and the baseline it produces.

## Known limitations

- **Logout does not revoke a copied session.** The API is stateless: a session is a signed token
  in an httpOnly cookie. Logging out clears the cookie in the browser, but a token someone had
  already copied stays valid until it expires (8 hours). Deactivating a user does take effect
  immediately, because the user is looked up on every request. Revoking tokens on logout would
  need a `token_version` column or a sessions table.
- **No login lockout or rate limiting yet.** Failed logins return one generic message, but they
  are not counted or throttled. This is planned for Stage 8 (it needs a database-backed counter,
  since the API keeps no in-memory state).
- **AI reading takes a few seconds and happens inside the upload request.** A normal manifest takes
  5 to 30 seconds; with a retry the worst case is about 95 seconds. There is no background queue.
- **Uploads are buffered by the web framework before the 10 MB check**, so a very large file is
  still received before it is refused. A production proxy should enforce its own request limit.
- **The AI makes some predictable mistakes.** In the eval it sometimes called fresh apples and
  carrots ambient (the prompt has no default storage rule), called UHT milk refrigerated, weighed
  "2 boxes" as one box, and resolved month-only or year-less dates incorrectly. Coordinators see
  and fix these on the review screen; prompt fixes are listed in `docs/dev-log.md`.
- **Rejected uploads are kept** (file, model output, who rejected and when) as an audit record.
