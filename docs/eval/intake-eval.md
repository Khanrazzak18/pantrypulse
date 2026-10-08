# Donation intake eval

- Run: 2026-10-08 16:23
- Model: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (Amazon Bedrock Converse, forced tool call, temperature 0)
- Golden set: 50 synthetic manifests (30 email, 15 pdf, 5 image)
- Target: field-level accuracy of at least 95%

## Result

**Field-level accuracy: 98.7%** (1,982 of 2,009 expected fields correct): **PASS**

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
| name | 287 of 287 | 100.0% |
| category | 285 of 287 | 99.3% |
| quantity | 287 of 287 | 100.0% |
| unit | 287 of 287 | 100.0% |
| estimated_weight_lbs | 282 of 287 | 98.3% |
| expiry_date | 281 of 287 | 97.9% |
| storage_type | 273 of 287 | 95.1% |

## Accuracy by format

| Format | Correct | Accuracy |
| --- | --- | --- |
| email | 1012 of 1022 | 99.0% |
| pdf | 841 of 854 | 98.5% |
| image | 129 of 133 | 97.0% |

## Token usage and time

| Measure | Value |
| --- | --- |
| Input tokens | 170,445 |
| Output tokens | 53,773 |
| Total tokens | 224,218 |
| Average per manifest | 3,408 in / 1,075 out |
| Average model latency | 5.3 s |
| Wall-clock time for the run | 70 s |

Token counts include answers that were rejected and retried.

## Scoring note

The first scoring of this run gave 92.9% (1,867 of 2,009 fields; 142 wrong). Most of that gap came from the answer key, not the model: it accepted only one name per food, so 'UHT milk', 'Popsicles', 'Oatmeal' and 'Romaine hearts' (the names printed in the manifests) counted as missed or misnamed items. The key now accepts every name a manifest may use for the same food. That turned 115 of the 142 wrong fields into correct ones and also revealed 7 real mistakes that the missed-item scoring had hidden.
This report scores the same saved model answers against the corrected key: 27 wrong fields remain, all listed under Mistakes. No model was called again and the prompt was not changed. The key was corrected after seeing the first result, so this is not a blind score. The golden set is synthetic and was written with the same rules as the prompt.

## How a field is scored

Each expected item has 7 fields. A field is correct if the model's matching item agrees:
name (same food, ignoring case, plurals and filler words), category, unit (after
normalising plurals and abbreviations), storage type and expiry date (exact; a missing
date is correct only if none was expected), quantity (within 1%) and estimated weight
(within 5%). An expected item the model missed counts as 7 wrong fields. Extra items are
reported but do not change the accuracy. Weights the manifest does not state are expected
to follow the typical case weights written in the prompt.

## Mistakes

- **001** (email) 'Tortillas': estimated_weight_lbs: expected `36`, got `18.0`
- **001** (email) '2% milk': category: expected `dairy`, got `beverages`
- **005** (email) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **010** (email) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **014** (email) 'Rice': expiry_date: expected `2028-05-27`, got `2028-05-31`
- **015** (email) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **015** (email) 'Chicken thighs': storage_type: expected `refrigerated`, got `frozen`
- **019** (email) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **023** (email) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **028** (email) 'Large eggs': estimated_weight_lbs: expected `480`, got `30.0`
- **032** (pdf) 'Carrots': storage_type: expected `refrigerated`, got `ambient`
- **034** (pdf) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **035** (pdf) 'Frozen pizza': expiry_date: expected `2027-06-02`, got `2026-06-02`
- **036** (pdf) 'Ground beef': storage_type: expected `refrigerated`, got `frozen`
- **038** (pdf) 'Shelf-stable milk': storage_type: expected `ambient`, got `refrigerated`
- **039** (pdf) 'Gala apples': storage_type: expected `refrigerated`, got `ambient`
- **039** (pdf) '2% milk': category: expected `dairy`, got `beverages`
- **040** (pdf) 'Shelf-stable milk': estimated_weight_lbs: expected `468`, got `154.8`
- **041** (pdf) 'Shelf-stable milk': estimated_weight_lbs: expected `380.0`, got `494.0`; storage_type: expected `ambient`, got `refrigerated`
- **041** (pdf) 'Frozen chicken breast': expiry_date: expected `2027-06-02`, got `2026-06-02`
- **042** (pdf) 'Shelf-stable milk': storage_type: expected `ambient`, got `refrigerated`
- **045** (pdf) 'Shelf-stable milk': estimated_weight_lbs: expected `300.0`, got `390.0`
- **046** (image) 'Frozen pizza': expiry_date: expected `2027-08-31`, got `2027-08-01`
- **046** (image) 'Sports drink': expiry_date: expected `2027-08-31`, got `2027-08-01`
- **049** (image) 'Carrots': storage_type: expected `refrigerated`, got `ambient`
- **050** (image) 'Rolled oats': expiry_date: expected `2028-05-27`, got `2028-05-31`
