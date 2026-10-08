"""The generator can hand back the true (uncensored) demand it simulated. It is for scoring a
forecast after the fact and must never be a training input."""

import numpy as np

from scripts.generate_synthetic_data import (
    DEFAULT_SEED,
    N_PANTRIES,
    N_WEEKS,
    fingerprint,
    generate,
    generate_with_truth,
)

# Pins the generator's output: refactoring it (Stage 5 moved the calendar rules) must not change
# the data the database was seeded with.
SEED_515_FINGERPRINT = "09181a39f193e7030bf34aa3be0fda5333c48579f489344fc6260d5ff8151b20"


def test_the_seeded_history_has_not_changed():
    assert fingerprint(generate(DEFAULT_SEED)) == SEED_515_FINGERPRINT


def test_truth_comes_with_exactly_the_same_data_as_generate():
    data, truth = generate_with_truth(DEFAULT_SEED)
    assert fingerprint(data) == SEED_515_FINGERPRINT
    assert truth.shape == (N_PANTRIES, 8, N_WEEKS) and (truth > 0).all()


def test_truth_is_reproducible_from_the_seed():
    _, first = generate_with_truth(DEFAULT_SEED)
    _, second = generate_with_truth(DEFAULT_SEED)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, generate_with_truth(DEFAULT_SEED + 1)[1])


def test_observed_pounds_never_exceed_true_demand_and_reported_shortages_fall_short():
    data, truth = generate_with_truth(DEFAULT_SEED)
    weeks = sorted({d["week_start"] for d in data.distributions})
    week_index = {w: i for i, w in enumerate(weeks)}
    reported = {(r["pantry_id"], r["category_id"], r["week_start"]) for r in data.shortage_reports}
    short_gap, capped = [], 0
    for d in data.distributions:
        demand = truth[d["pantry_id"] - 1, d["category_id"] - 1, week_index[d["week_start"]]]
        assert d["lbs"] <= demand + 0.01  # supply can cap demand but never add to it
        if (d["pantry_id"], d["category_id"], d["week_start"]) in reported:
            short_gap.append(d["lbs"] / demand)
            capped += 1
    assert capped == len(data.shortage_reports)
    assert max(short_gap) < 0.9 + 1e-6  # a report is only filed below 90% of demand
