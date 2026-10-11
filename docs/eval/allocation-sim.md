# Allocation simulation

- Run: 2026-10-11 16:14
- Window: 12 weeks, 2026-07-13 to 2026-09-28 (the weeks of backtest run 1); food goes out on Wednesday and Friday
- Stock: 330 lots, 5,585,070 lb usable, arriving on their real received dates; the warehouse starts empty and unshipped stock carries over
- Pantries: 85; true demand comes from the data generator and is used only to score the result (and by the manual rule, below)

## What this simulation can and cannot tell us

**It can test the stockout target. It cannot test the spoilage target.**

The stockout comparison is meaningful in principle because the data generator's *demand* is real structure the policies must respond to: a policy that sends food where it is needed meets more demand, and one that guesses wrong leaves pantries short. How much the optimizer helps depends on how good the manual rule is assumed to be, which nobody has measured; see the results and sensitivity tables.

The spoilage target (12% down to under 8%) cannot be tested on this data, because the generator draws spoilage for each lot independently of how the food is allocated: how much of a lot expires is decided when the lot is created, before any allocation exists. Allocation therefore has no way to change the spoilage in the history, and the 12% baseline is a property of the generator's settings, not of anyone's allocation decisions. The spoilage numbers below come only from the simulation's own bookkeeping of food that expires in the warehouse or is sent in excess of need. They are reported for completeness, are not evidence for or against the 8% target, and should not go into a grant report.

**What a real pilot would need to measure to test spoilage:**

- Lot-level records of pounds received, pounds shipped to pantries, pounds distributed to households and pounds discarded, each with its date, for the period before the optimizer is used (at least one season) and during the pilot.
- The cause of every discard (expired in the warehouse, expired at the pantry, damaged), so spoilage caused by allocation can be separated from spoilage that no allocation could have prevented.
- A comparison that controls for what was donated: pilot pantries or counties against comparison pantries in the same weeks, or a stepped rollout across pantries, with the perishable mix and shelf life at receipt recorded.
- Pantry-side reports of food that expired after delivery, since sending food to a pantry that cannot use it in time only moves the waste.

## Results

Primary setup: deliveries on Wednesday and Friday. Manual rule: mean of 10 runs (range in brackets). Optimizer: one run (it is deterministic).

| Measure | Manual rule | Optimizer | Change |
| --- | --- | --- | --- |
| Pantry-weeks with a shortage (any category under 90% of demand) | 31.3% (29.9% to 33.8%) | 34.8% | +11% |
| Pantry-category-weeks short | 4.4% (4.3% to 4.8%) | 6.2% | +42% |
| Perishable loss, definition A (expired in the warehouse plus sent beyond need) | 13.7% (13.7% to 13.8%) | 14.1% | +3% |
| Perishable loss, definition B (expired in the warehouse only) | 0.0% (0.0% to 0.0%) | 3.8% | n/a |

**Stockout target (30% fewer shortages): not met (the optimizer was not better than the manual rule).** Pantry-weeks with a shortage went from 31.3% to 34.8%, a change of +11.0%.

Why the optimizer still runs short: 58% of its short pantry-category-weeks were weeks when true demand was above the P90 forecast, which the optimizer never sends beyond (a rule of the design). The manual rule is not capped, and on average it ships 119% of true demand because the stock on hand exceeds demand in these data.

Spoilage: no verdict, for the reason above. Definition A counts food that expires in the warehouse plus food sent to a pantry beyond its true demand (assumed to go to waste). Definition B counts only warehouse expiry, which flatters the manual rule because it ships everything the day it is decided, so little waits long enough to expire. The optimizer keeps stock back when pantries are already covered up to their P90 forecast, which is why B can be higher for it. Both are shown so neither choice hides the other.

## The result depends on the assumptions

Pantry-weeks with a shortage, under different delivery schedules and two versions of the manual rule. "Netted" is a coordinator who also remembers what already went out that week when splitting the Friday delivery.

| Schedule | Manual (as above) | Manual, netted | Optimizer |
| --- | --- | --- | --- |
| Wednesday and Friday (primary) | 31.4% | 18.0% | 34.8% |
| Friday only (everything that arrived Monday to Friday) | 57.4% | 57.4% | 46.2% |
| Wednesday only (stock that arrived by Wednesday) | 99.9% | 99.9% | 100.0% |

The optimizer had fewer shortage pantry-weeks than the manual rule in 1 of 3 schedules, and than the netted manual rule in 1 of 3. So this simulation does not give a robust stockout reduction of 30%: the size of the effect, and its sign, depends on how good the current process is and how often food goes out, neither of which has been measured. A pilot would have to measure them.

Wednesday-only delivery is shown to make a point, not as a plan: short-lived stock that arrives on Thursday or Friday expires before the next Wednesday, so both policies look far worse. That is a scheduling effect, not an allocation one.

## Sensitivity to the manual rule's error

The manual rule's error is an assumption (how well a coordinator's split follows true demand). Primary schedule, pantry-weeks with a shortage:

| Error (lognormal sigma) | Manual | Optimizer |
| --- | --- | --- |
| 0.00 | 0.0% | 34.8% |
| 0.15 | 31.4% | 34.8% |
| 0.30 | 77.8% | 34.8% |
| 0.50 | 95.4% | 34.8% |

The 0.15 used above is a judgment, not a measurement of Harvest Bridge's coordinators. For scale, the seasonal-naive baseline in the forecast backtest, which is roughly what a person working from last year's numbers could do, has an error of about 14%.

## Method notes and limits

- A pantry is short in a category when it receives under 90% of that week's true demand.
- Manual rule: ships everything on hand, split between pantries in proportion to true demand times a lognormal error. It uses true demand, which no coordinator has; the optimizer uses only the forecasts the backtest made before each week. This favors the manual rule on information.
- The manual rule ignores pantry storage capacity; the optimizer respects it.
- Food goes out on Wednesday, and again on Friday for lots that arrived since (a re-run, as in the app: forecasts and pantry capacity are net of what already went). A lot that arrives on the weekend waits for the next Wednesday. Food a pantry gets beyond its true demand counts as lost in definition A.
- Perishable percentages are of perishable pounds that were shipped or expired during the window (2,867,927 lb for the optimizer); stock still in the warehouse at the end is left out so neither policy is charged for food it has not had time to handle.
- The one optimizer setting chosen with help from this simulation is the reward for demand between P50 and P90 (0.5 of a pound's value). A prototype compared 0, 0.3, 0.6 and 0.9 on this same data, and 0 (aim at P50 only) was clearly worse. The other weights (urgency, distance) were set by reasoning and not tuned. The result therefore is not an untouched out-of-sample test of the optimizer.
- Demand, supply and spoilage are synthetic. These numbers show how the method behaves on a simulated food bank, not what Harvest Bridge would see.
