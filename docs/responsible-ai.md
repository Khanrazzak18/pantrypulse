# Responsible AI

How PantryPulse uses AI, what it is not allowed to do, how fairness was measured, and what is still
imperfect. The AI never decides anything on its own: it reads documents, writes sentences and
suggests numbers, and a person approves each result.

## Where AI is used

| Feature | What the model does | What a person does | What the model sees |
| --- | --- | --- | --- |
| Donation intake | Reads an email, PDF or photo into line items with a confidence per field | Edits and confirms every donation before it enters inventory | The manifest itself (which may name a donor) and today's date |
| Allocation reasons | Writes a one-line reason for each shipment the optimizer chose | Approves, edits or rejects each shipment | Per shipment: pantry name, county, category, forecast pounds, miles, item name, days to expiry |
| Monthly summary | Drafts a paragraph for grant reports | An administrator edits and approves the final text | Aggregated monthly totals only, never individual records |

The forecast (LightGBM) and the allocation (a linear program) are ordinary statistics and
optimisation, not generative AI. Neither can be changed by anything a model writes.

## 1. Human review

- **Donations:** nothing enters inventory until a coordinator confirms the list. The AI's output is stored as a
  pending donation only (`pending_review`).
- **Allocations:** the optimizer proposes; a coordinator approves, edits or rejects each row (or approves the rows
  currently shown, after a confirmation dialog that states how many shipments and pounds). Stock is taken out only on approval.
- **Summaries:** the draft is editable text; an administrator approves it before it is saved as final.
- The footer on every page says: "AI suggestions are reviewed by staff before anything is sent."
- The code enforces this rather than relying on policy: the model has exactly one tool per call (a data-return tool that
  is forced), it has no tool that writes data, and the only code path that creates inventory is the coordinator's confirm
  request. Tests: `test_llm_safety.py`, `test_donations_review.py`.

## 2. Transparency

- **AI or template.** Every allocation reason is labelled "AI" or "Template" (the sentence the app builds itself when the
  model call fails or is skipped). Hovering explains which.
- **Model and cost.** A donation shows which model read it, how long it took and the token counts; the model id is configured in one
  place (`BEDROCK_MODEL_ID`) and stored with each donation.
- **Confidence.** Intake returns a 0 to 1 confidence for every field. Fields under 80% are highlighted, listed ("AI unsure
  (60%)") and counted at the top of the review page, and a note from the AI is shown when it has one.
- **Why a shipment.** Each shipment shows its reason, the lot's expiry and how much is left in the lot; edits show the
  original proposal ("proposed 120 lb").
- **Accuracy is published.** `docs/eval/` holds the intake accuracy, the forecast backtest (model against last year's value),
  the allocation simulation and the fairness results, including targets that were not met.

## 3. Data minimisation

- The model gets the least it needs (table above). Allocation prompts carry pantry and item names, not people; summary
  prompts carry totals. No user, household or login data is ever sent.
- Uploads are limited to six types and 10 MB, stored by a random name behind a storage interface, and never served back by any route.
- **Retention.** The model's raw output is kept as audit evidence of what it said versus what a person confirmed, then cleared
  **90 days after review** by the weekly refresh (`raw_output_cleared_at` records when; pending donations are never cleared).
  Model id, latency, token counts, the confirmed items and every edit stay.
- Logs never contain request bodies, passwords, tokens or database values.

## 4. Guardrails

- **Schema validation.** Every model response is validated against a Pydantic schema; invalid output is retried once and
  then reported as an error the screen can show. Extra fields the model invents are dropped (and tested not to reach the database); bad categories, impossible weights and over-long text are refused.
- **Number checks.** Allocation reasons and summaries may only contain numbers the model was given (give or take rounding).
  A draft that invents a number is rejected and the app falls back to a template sentence or asks the administrator to retry.
- **Prompt injection.** Manifest text is placed in the user turn as untrusted data with a system prompt that says so; the model
  has one forced data-return tool and a call to any other tool is ignored. Tests prove a hostile manifest creates one pending
  donation and changes no other record, and a live run against the real model with three injection manifests produced only the
  legitimate items (`docs/security/injection-check.md`).
- **Limits.** Output tokens and request time are capped inside the provider for every call; AI endpoints are rate limited per user.
- **Safe display.** AI text is shown as text, never as HTML; a hostile name or note cannot run script.

## 5. Fairness

Question: does allocation treat pantries fairly? Measure: the **share of P50 demand met** by county (6), by distance from the
warehouse (near, middle, far) and by pantry size (small, medium, large), judged against a rule that **no group may be served more than
10 percentage points below the all-pantry average**. Full tables, method and the trade-off are in
[`docs/eval/fairness.md`](eval/fairness.md); `make fairness` reproduces them (no AWS, no database writes).

| Case | Before (single reward per pound) | After (tiered coverage) |
| --- | --- | --- |
| Latest allocation run, stock on hand | every group 100% | unchanged |
| 12-week simulation, normal stock | worst group -0.6 pp (size: small) | worst group -0.4 pp (county: Ashford) |
| 12-week simulation, **half stock** | **far pantries 1.4% met, -59.4 pp; Elmhurst county -25.3 pp** | far band 56.9%, **-3.9 pp**; worst county -1.5 pp |

**Fairness was only visible under scarcity.** With normal stock every pantry's forecast is met in full, groups differ by under one
point, and the check passes whatever the objective is. Distance never mattered because there was enough for everyone. When stock was
halved, the old objective gave every pound the same value, so the only thing separating pantries was a small penalty per mile; that
penalty became the only tie-breaker and the nearest pantries were filled completely before the farthest band received almost
nothing. A food bank is exactly the place where supply is short: the week the truck is late, the donation falls through or the
produce spoils is the week fairness matters, and it is the week a test on normal stock would never show.

**The fix.** Each pantry's P50 forecast is split into ten slices and each slice is worth 0.02 less per pound than the one before (and
always more than the largest distance difference between any two pantries). A pound is therefore worth most to the pantry that has
received the smallest share of its own forecast, so scarce stock is spread by share of demand. Distance still breaks ties between
equally covered pantries; it can no longer outweigh unmet demand. Overall demand met is unchanged (60.8% in the half-stock case).

**What it costs, honestly:**
- When stock is short, pound-miles rise about 20% (53.1 to 63.6 million) and trip miles about 80%, because far pantries now receive food.
- **More pantries are short.** A pantry counts as short when any category gets under 90% of true demand. The old objective
  concentrated a shortage on a few far pantries and kept the rest whole; the new one gives everyone a similar partial share. Even in
  the normal simulation, short pantry-weeks rose from 33.2% to 34.8%. `docs/eval/allocation-sim.md` already reported its stockout
  target as not met; this widens that gap slightly and that report states it. The worst-served pantry's share rises from 0% to about 55% in the half-stock case.
- A gentler version (fairness slices on only the first 30, 50 or 70% of each forecast) was tried and rejected: it protected far pantries
  less and did not avoid the rise in short pantry-weeks.

**What fairness means here.** Equal share of each pantry's *forecast* demand. It is not weighted by need, income or access, and the
synthetic data has no real differences between counties or sizes. If the food bank wants to favour higher-need pantries, that is a policy
decision for the coordinators and a weight in the optimizer; it should not be hidden in a model.

## 6. Accountability

- Every change a coordinator makes to a proposed shipment is stored with the old value, the new value, who did it and when
  (`allocation_edits`); approvals and rejections store the user and time on the shipment.
- Donations record who reviewed them and when; monthly summaries record who approved the final text, and keep the AI draft next to it.
- Every API request and every model call is logged as structured JSON with a request id, model id, latency and token counts.
- Sessions can be revoked, access is checked by role on every route (an automated test walks every route as every role), and the security
  audit is in `docs/security/audit.md`.

## 7. Limitations

- **The model makes mistakes the checks cannot see.** Intake leaves a few wrong dates and weights; reasons and summaries are checked for invented numbers, not for a wrong label on a real number.
  This is why a person approves each result.
- **The tests use synthetic data.** Accuracy, spoilage and fairness figures show the method works on a realistic simulation, not what the food bank will see.
- **Fairness is one definition** (equal share of forecast), measured by county, distance and size only. It does not look at need, language, transport or individual households.
- **Forecasts under-serve the unforeseen.** Demand above the P90 forecast is never sent to a pantry; the weekly shortage report is how the system learns it was wrong.
- **Manifests are untrusted.** Injection defences are strong against what was tested, but no test can prove every attack fails; that is the reason the model cannot write data and a person confirms.
- **No screen-reader testing by a person** has been done yet (see `docs/accessibility.md`), and the model cannot be fully audited: it is a hosted service whose version can change.
