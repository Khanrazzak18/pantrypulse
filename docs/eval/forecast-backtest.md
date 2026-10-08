# Demand forecast backtest

- Run 2 on 2026-10-08 17:09; 12 weekly origins, 2026-07-13 to 2026-09-28; 8,160 pantry-category-week forecasts over 680 series.
- LightGBM 4.7.0, Python 3.13.9; the backtest took 55 s.
- Target: WAPE under 20% per pantry and category.

## Overall accuracy

WAPE is total absolute error divided by total actual pounds. **Observed** is what pantries actually handed out, which supply caps in shortage weeks, so it is what can be measured in real life. **True demand** is what the simulator generated before supply capped it; it exists only because the data is synthetic and was never used to train anything.

| Model | WAPE vs observed | WAPE vs true demand | Series under 20% (observed) |
| --- | --- | --- | --- |
| Baseline | 14.5% | 14.3% | 95.4% |
| LightGBM | 10.7% | 10.2% | 99.9% |
| LightGBM, no correction | 10.7% | 10.2% | 99.9% |

LightGBM meets the 20% target overall against observed pounds (10.7%, versus 14.5% for the baseline). The median series has a WAPE of 10.5% (baseline 14.2%); 99.9% of series are under 20% (baseline 95.4%).

### Prediction interval (P10 to P90)

| Measure | Value |
| --- | --- |
| Coverage of observed pounds (ideal: 80%) | 77.2% |
| Coverage of true demand | 79.2% |
| Average interval width (P90 - P10, as a share of P50) | 32.5% |

### Does the censoring correction help?

Against true demand the corrected model scores 10.2% and the same model trained on raw observed pounds scores 10.2%: no measurable difference. In the 244 forecasts for weeks with a shortage report, the corrected model scores 11.6% against true demand and the uncorrected one 11.8%. Shortage reports cover only 3.0% of forecasts, so even a large uplift on those rows moves the overall figure little.

### Reading the two columns

Observed pounds are capped by supply, so a model that forecasts true demand is judged against a smaller number in shortage weeks and looks worse against observed than against true demand. The 'no correction' row shows what the censoring correction is worth: it is the same model trained on raw observed pounds. Its WAPE against true demand is the fair comparison.

## Leakage checks

A forecast for week t may only use what is known at the start of week t. Each row is one way future information could get in, how it is prevented, and the evidence. Tests are in `backend/tests/`.

| # | Rule | How it is enforced | Evidence |
| --- | --- | --- | --- |
| L1 | The forecast for week t is made at the start of week t, so only data through week t-1 exists. | Each backtest origin is a Monday; the model is handed only earlier weeks. | Assertions inside run_backtest on every fold (history and training rows end before the origin). `test_forecast_model::test_each_fold_trains_only_on_weeks_before_its_target_week` |
| L2 | The panel given to the feature builder contains no week from t onward. | build_frame refuses any panel whose last week is not before the forecast week. | Unit test and the fold assertions. `test_forecast_features::test_the_forecast_week_must_come_after_the_data` |
| L3 | The week being forecast carries no observations (pounds, households, shortage report, weather). | The target week is an empty row per series, created after the history is fixed. | Unit test: every observed column is empty for the target week. `test_forecast_features::test_the_target_week_has_one_row_per_series_and_no_observations` |
| L4 | Lag and rolling-mean features look strictly backwards. | Lags are shifts of 1 week or more; rolling windows are computed on the already-shifted series, so a window never holds the week itself. | Exact values on a ramp series, and a test that replaces a week's own data with garbage and checks its features do not move. `test_forecast_features::test_lags_and_rolling_means_on_a_ramp`; `test_forecast_features::test_a_weeks_own_observations_never_appear_in_its_features` |
| L5 | A missing week is a gap, never filled by shifting older values forward. | Every series is reindexed to a complete weekly grid before shifting. | Unit test with a deleted week. `test_forecast_features::test_a_missing_week_leaves_a_gap_instead_of_shifting_older_values_forward` |
| L6 | The weather of the forecast week is not a feature (in practice only a weather forecast would exist). | Only last week's weather and a climatology made of the same week one and two years earlier (lags of 52 and 104 weeks) are used. | Unit test of the values; the weather columns of the target week are empty. `test_forecast_features::test_weather_features_are_last_weeks_weather_and_the_climatology` |
| L7 | School-holiday and benefit-week flags of the forecast week are used. JUDGEMENT CALL for review: they are scheduled in advance, so they are knowable at forecast time. | Stored flags for past weeks; the calendar rules (app/services/calendar_rules.py) for weeks with no stored row. | Unit tests for both sources. `test_forecast_features::test_calendar_flags_for_a_week_with_no_data_come_from_the_rules`; `test_forecast_features::test_calendar_flags_for_past_weeks_come_from_the_stored_data` |
| L8 | Static features (pantry, category, baseline households) do not change over time. | Taken once per pantry from the pantries table. baseline_households is a constant in this data. | Design (no time-varying source); listed so a reviewer can challenge it. `test_forecast_features::test_every_feature_is_defined_for_target_weeks_without_data` |
| L9 | No raw current-week column is a model input. | FEATURES is a fixed list; the training function asserts it is disjoint from the current-week columns. | Unit test on the list, and an assertion in fit_models. `test_forecast_features::test_no_raw_current_week_column_is_a_feature` |
| L10 | The model learns only from weeks before the origin. | training_rows keeps weeks earlier than the target week; each fold asserts the latest training week is before the origin. | Unit test and the per-fold assertion. `test_forecast_features::test_training_rows_are_before_the_target_week_with_a_known_target` |
| L11 | The training target for week s is built only from week s's own shortage report and household visits (both known by the end of week s, before any later origin). | The correction is a row-wise formula; nothing from other weeks enters it. | Unit tests of the formula and of its scope. `test_forecast_censoring::test_the_correction_applies_to_shortage_weeks_only` |
| L12 | A shortage report cannot spread to other weeks, categories or pantries. | The correction is keyed on the exact (pantry, category, week) of the report. | Unit test with neighbours. `test_forecast_censoring::test_a_report_in_another_week_or_category_does_not_leak_onto_its_neighbours` |
| L13 | Nothing learned at one origin is carried to the next. | Every origin builds its features and trains fresh models from scratch. | Code structure of run_backtest; more training rows at each later origin. `test_forecast_model::test_each_fold_trains_only_on_weeks_before_its_target_week` |
| L14 | No tuning, early stopping or model selection on the backtest weeks. | All hyperparameters are fixed in ForecastConfig before the first run; training uses a fixed tree count and a fixed seed. | The configuration is printed in this report; training is deterministic. `test_forecast_model::test_training_is_deterministic` |
| L15 | The seasonal-naive baseline reads only observations from 52 weeks earlier. | It is a 52-week shift of observed pounds (not corrected demand). | Unit tests on a tiny fixture. `test_forecast_baseline::test_baseline_is_the_observed_value_52_weeks_earlier`; `test_forecast_baseline::test_baseline_never_peeks_forward` |
| L16 | Actuals are attached only after predictions exist, and are used only for scoring. | run_backtest merges observed pounds onto the finished predictions. | Unit test comparing every checked row with the panel. `test_forecast_model::test_actuals_and_baseline_in_the_backtest_come_from_the_panel` |
| L17 | The simulator's true demand is never a training input. | The forecasting module does not import the generator, nothing under app/ uses it, no training function takes a truth argument. Only this script reads it, after the backtest, to report a second WAPE. | Static checks of imports and signatures. `test_forecast_leakage::test_the_forecasting_module_does_not_import_the_generator_or_its_truth`; `test_forecast_leakage::test_nothing_in_the_app_package_uses_the_latent_demand`; `test_forecast_leakage::test_no_training_or_prediction_function_accepts_a_truth_argument`; `test_forecast_leakage::test_the_only_user_of_the_truth_is_the_evaluation_script` |
| L18 | Overwriting the future with garbage changes no earlier prediction. | The backtest is run twice, once with every week from week 64 onward replaced by 1e9 values; predictions for earlier origins must be identical. | End-to-end test, plus the same probe on the real data in this run (below). `test_forecast_model::test_overwriting_the_future_with_garbage_changes_no_earlier_prediction`; `test_forecast_features::test_features_are_identical_whether_or_not_later_weeks_exist` |
| L19 | No statistic computed from test rows enters training (no target encoding, scaling or imputation from the test weeks). | The only transform is log(1 + demand) on the training target, which has no parameters. Missing values are left to LightGBM. | Design; listed so a reviewer can challenge it. `test_forecast_model::test_the_target_is_demand_not_a_leaked_copy_of_a_feature` |

**Probe on this run's real data:** the last 3 weeks of the database were replaced with garbage values (1e9 pounds, households and weather; a severity-3 shortage with 1e9 households turned away), and the features of every earlier week (104,720 rows x 21 features) were compared with features built from the untouched earlier data alone: **no difference**.

**Runtime assertions:** every one of the 12 folds asserted that the history it was given and its training rows end before its origin, and that no current-week column is a feature; the run would have stopped otherwise.

## Method

- **Target:** weekly demand in pounds per pantry and category, predicted one week ahead. Trained on `log(1 + demand)`, with P10, P50 and P90 as separate LightGBM quantile models (P50 is the median, which is what WAPE rewards). Predictions are un-logged, clipped at 0 and sorted so P10 <= P50 <= P90.
- **Censored demand:** when a pantry ran short of a category in a week and filed a report, the training target is `observed / (1 - shortfall)`, with `shortfall = min(0.5, max(prior[severity], households turned away / households visiting))` and priors of 10%, 25% and 50% for severity 1, 2, 3. Weeks without a report are left as observed. The constants are assumptions.
- **Features:** `lag1`, `lag2`, `lag3`, `lag4`, `lag52`, `rm4`, `rm12`, `hh_lag1`, `hh_rm4`, `short_lag1`, `short_cnt4`, `shortfall_lag1`, `temp_lag1`, `precip_lag1`, `temp_clim`, `woy`, `school_holiday`, `benefit_week`, `baseline_households`, `pantry_id`, `category_id`.
- **Baseline:** the pounds observed in the same week 52 weeks earlier.
- **Backtest:** rolling origin over the last 12 weeks. Each origin refits from scratch on all earlier weeks (95,200 to 102,680 training rows).
- **Fixed settings:** 300 trees, learning rate 0.05, 31 leaves, min 50 rows per leaf, feature fraction 0.8, bagging 0.8, seed 1. Chosen before any backtest and not tuned on these weeks.

## By category

| Group | Forecasts | LightGBM | Baseline | No correction | LightGBM vs true | No correction vs true |
| --- | --- | --- | --- | --- | --- | --- |
| produce | 1,020 | 11.2% | 15.7% | 11.3% | 10.6% | 10.6% |
| dairy | 1,020 | 11.0% | 14.1% | 10.9% | 10.2% | 10.1% |
| protein | 1,020 | 10.7% | 15.1% | 10.6% | 9.8% | 9.9% |
| bakery | 1,020 | 10.4% | 14.2% | 10.3% | 10.0% | 9.9% |
| frozen | 1,020 | 10.3% | 13.9% | 10.3% | 9.8% | 9.7% |
| canned | 1,020 | 9.7% | 13.6% | 9.7% | 9.6% | 9.6% |
| dry_goods | 1,020 | 10.9% | 13.9% | 10.8% | 10.6% | 10.6% |
| beverages | 1,020 | 10.7% | 14.1% | 10.7% | 10.2% | 10.1% |

## Weeks with a shortage report vs without

| Group | Forecasts | LightGBM | Baseline | No correction | LightGBM vs true | No correction vs true |
| --- | --- | --- | --- | --- | --- | --- |
| Weeks with a shortage report | 244 | 17.4% | 18.9% | 17.4% | 11.6% | 11.8% |
| Weeks without one | 7,916 | 10.5% | 14.4% | 10.4% | 10.1% | 10.1% |

## Each origin

| Week forecast | Training rows | Trained through | LightGBM | Baseline | Coverage | Seconds |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-13 | 95,200 | 2026-07-06 | 10.3% | 13.7% | 80.6% | 5.0 |
| 2026-07-20 | 95,880 | 2026-07-13 | 11.1% | 14.8% | 76.3% | 4.5 |
| 2026-07-27 | 96,560 | 2026-07-20 | 10.5% | 15.2% | 76.9% | 4.5 |
| 2026-08-03 | 97,240 | 2026-07-27 | 10.7% | 14.3% | 75.0% | 4.5 |
| 2026-08-10 | 97,920 | 2026-08-03 | 10.9% | 14.9% | 74.6% | 4.5 |
| 2026-08-17 | 98,600 | 2026-08-10 | 10.4% | 13.1% | 79.7% | 4.5 |
| 2026-08-24 | 99,280 | 2026-08-17 | 10.4% | 14.5% | 77.8% | 4.4 |
| 2026-08-31 | 99,960 | 2026-08-24 | 11.1% | 13.8% | 74.7% | 4.5 |
| 2026-09-07 | 100,640 | 2026-08-31 | 10.7% | 14.3% | 78.5% | 4.5 |
| 2026-09-14 | 101,320 | 2026-09-07 | 10.7% | 13.8% | 76.5% | 4.7 |
| 2026-09-21 | 102,000 | 2026-09-14 | 11.1% | 14.9% | 75.1% | 4.4 |
| 2026-09-28 | 102,680 | 2026-09-21 | 10.2% | 16.6% | 80.4% | 4.7 |

## Hardest series

| Pantry | Category | Average weekly lb | LightGBM | Baseline |
| --- | --- | --- | --- | --- |
| 12 | dairy | 378 | 20.9% | 18.4% |
| 49 | bakery | 252 | 18.7% | 13.7% |
| 25 | dairy | 52 | 18.5% | 13.7% |
| 21 | produce | 696 | 17.8% | 26.5% |
| 41 | protein | 411 | 17.8% | 22.5% |
| 7 | frozen | 281 | 17.1% | 20.8% |
| 15 | protein | 812 | 16.9% | 21.8% |
| 73 | protein | 325 | 16.8% | 21.7% |
| 76 | produce | 793 | 16.8% | 19.7% |
| 14 | protein | 103 | 16.5% | 14.2% |

## Assumptions and limits

- The data is synthetic. Its demand follows seasonality, school holidays, benefit weeks, weather and noise that the model's features describe, so accuracy here is likely better than on real manifests.
- The shortage correction uses assumed constants. Only reported shortages are corrected (pantries report some of the weeks they run short), so some demand stays under-recorded.
- Only 12 weekly origins are scored, with one data seed; 12 weeks is too few to say anything about seasonality in the errors.
- WAPE for a single pantry and category rests on 12 numbers and can be dominated by one week.
- The forecast uses last week's weather and a climatology, not the weather of the week being forecast; a real weather forecast could be added as a feature.
- School-holiday and benefit-week flags are known schedules (check L7).
- Database matches the generator seed: yes.

## Reproduce

```
make backtest
```
