# Donation intake eval

- Run: 2026-10-08 18:21
- Model: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Amazon Bedrock Converse, forced tool call, temperature 0)
- Golden set: 50 synthetic manifests (30 email, 15 pdf, 5 image)
- Target: field-level accuracy of at least 95%

## Result

**Field-level accuracy: 99.5%** (1,999 of 2,009 expected fields correct): **PASS**

| Measure | Value |
| --- | --- |
| Items found | 287 of 287 (100.0%) |
| Extra items invented | 0 |
| Donor name correct | 50 of 50 |
| Manifests that failed outright | 0 |
| Manifests that needed the retry | 0 |

## Accuracy by field

| Field | Correct | Accuracy |
| --- | --- | --- |
| name | 286 of 287 | 99.7% |
| category | 287 of 287 | 100.0% |
| quantity | 287 of 287 | 100.0% |
| unit | 287 of 287 | 100.0% |
| estimated_weight_lbs | 285 of 287 | 99.3% |
| expiry_date | 282 of 287 | 98.3% |
| storage_type | 285 of 287 | 99.3% |

## Accuracy by format

| Format | Correct | Accuracy |
| --- | --- | --- |
| email | 1020 of 1022 | 99.8% |
| pdf | 849 of 854 | 99.4% |
| image | 130 of 133 | 97.7% |

## Token usage and time

| Measure | Value |
| --- | --- |
| Input tokens | 191,145 |
| Output tokens | 53,703 |
| Total tokens | 244,848 |
| Average per manifest | 3,822 in / 1,074 out |
| Average model latency | 5.3 s |
| Wall-clock time for the run | 70 s |

Token counts include answers that were rejected and retried.

## Results history

| Run | Prompt | Answer key | Accuracy |
| --- | --- | --- | --- |
| 1 (Stage 4) | first | first key | 92.9% (1,867 of 2,009) |
| 1, rescored | first | corrected after seeing run 1 | 98.7% (1,982 of 2,009) |
| 2 (Stage 8) | with the Stage 8 fixes | frozen (`eval/golden/KEY.sha256`) | see Result above |

How much to trust run 2: the key was frozen and committed before the prompt changed, and `make eval` refuses to run if it differs, so nobody could help the score by editing answers. It is still not a blind test. The prompt fixes (default storage by food, milk, weights per unit, month-only and year-less dates) were written to cure mistakes seen on this same set in run 1, using different example foods, and the set is synthetic and was written with the same rules as the prompt. Read it as 'the known mistakes are fixed', not as accuracy on real manifests. It is one run at temperature 0; a different run could differ by a field or two.

## How a field is scored

Each expected item has 7 fields. A field is correct if the model's matching item agrees:
name (same food, ignoring case, plurals and filler words), category, unit (after
normalising plurals and abbreviations), storage type and expiry date (exact; a missing
date is correct only if none was expected), quantity (within 1%) and estimated weight
(within 5%). An expected item the model missed counts as 7 wrong fields. Extra items are
reported but do not change the accuracy. Weights the manifest does not state are expected
to follow the typical case weights written in the prompt.

## Mistakes

- **005** (email) 'Frozen meals': expiry_date: expected `2027-06-30`, got `2027-06-01`
- **009** (email) 'Tomato soup': estimated_weight_lbs: expected `44.0`, got `88.0`
- **038** (pdf) 'Ground beef': storage_type: expected `refrigerated`, got `frozen`
- **039** (pdf) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **040** (pdf) 'Frozen mixed vegetables': name: expected `Frozen mixed vegetables`, got `Vegetable mix`
- **041** (pdf) 'Shelf-stable milk': estimated_weight_lbs: expected `380.0`, got `494.0`
- **044** (pdf) 'Black beans': expiry_date: expected `2029-01-31`, got `2029-01-01`
- **046** (image) 'Frozen pizza': expiry_date: expected `2027-08-31`, got `2027-08-01`
- **046** (image) 'Sports drink': expiry_date: expected `2027-08-31`, got `2027-08-01`
- **050** (image) 'Rolled oats': expiry_date: expected `2028-05-27`, got `2028-05-31`
