"""allocation workflow: run metadata, reason source, decision rules, audit field list

Allocation runs now record the forecast week they cover, the planned delivery date, how many lots
were considered and how the reasons were written. Allocations record where their reason came from
and may not duplicate a lot and pantry within a run; a decided allocation must carry its quantity
and delivery date. Alembic does not detect CHECK constraints, so they are written out by hand.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- allocation_runs ---
    op.add_column("allocation_runs", sa.Column("week_start", sa.Date(), nullable=True))
    op.add_column("allocation_runs", sa.Column("delivery_date", sa.Date(), nullable=True))
    # Any run created before this migration inherits its forecast run's week.
    op.execute(
        "UPDATE allocation_runs r SET week_start = f.horizon_week_start, "
        "delivery_date = f.horizon_week_start FROM forecast_runs f WHERE f.id = r.forecast_run_id"
    )
    op.alter_column("allocation_runs", "week_start", nullable=False)
    op.alter_column("allocation_runs", "delivery_date", nullable=False)
    for name, kind in (
        ("lots_considered", sa.Integer()),
        ("lots_excluded", sa.Integer()),
        ("reasons_ai", sa.Integer()),
        ("reasons_template", sa.Integer()),
    ):
        op.add_column("allocation_runs", sa.Column(name, kind, server_default="0", nullable=False))
    op.add_column(
        "allocation_runs",
        sa.Column("shipped_lbs", sa.Numeric(14, 2), server_default="0", nullable=False),
    )
    op.add_column("allocation_runs", sa.Column("reason_model_id", sa.String(120), nullable=True))
    op.add_column("allocation_runs", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("allocation_runs", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("allocation_runs", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_allocation_runs_week_is_monday"),
        "allocation_runs",
        "extract(isodow from week_start) = 1",
    )
    op.create_check_constraint(
        op.f("ck_allocation_runs_delivery_within_week"),
        "allocation_runs",
        "delivery_date >= week_start AND delivery_date <= week_start + 6",
    )
    op.create_check_constraint(
        op.f("ck_allocation_runs_counts_nonneg"),
        "allocation_runs",
        "lots_considered >= 0 AND lots_excluded >= 0 AND reasons_ai >= 0 "
        "AND reasons_template >= 0 AND shipped_lbs >= 0",
    )

    # --- allocations ---
    op.add_column(
        "allocations",
        sa.Column("reason_source", sa.String(10), server_default="template", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_allocations_reason_source_valid"),
        "allocations",
        "reason_source IN ('ai', 'template')",
    )
    # Decisions made before this migration (none in practice) get a delivery date to satisfy the rule.
    op.execute(
        "UPDATE allocations a SET delivery_date = r.delivery_date FROM allocation_runs r "
        "WHERE r.id = a.allocation_run_id AND a.status IN ('approved', 'edited') "
        "AND a.delivery_date IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_allocations_decision_fields"),
        "allocations",
        "(status = 'proposed' AND final_lbs IS NULL AND delivery_date IS NULL) "
        "OR (status IN ('approved', 'edited') AND final_lbs IS NOT NULL AND final_lbs > 0 AND delivery_date IS NOT NULL) "
        "OR (status = 'rejected' AND final_lbs IS NULL AND delivery_date IS NULL)",
    )
    op.create_unique_constraint(
        op.f("uq_allocations_allocation_run_id_lot_id_pantry_id"),
        "allocations",
        ["allocation_run_id", "lot_id", "pantry_id"],
    )
    op.create_index("ix_allocations_lot_id", "allocations", ["lot_id"], unique=False)

    # --- allocation_edits ---
    op.create_check_constraint(
        op.f("ck_allocation_edits_field_valid"),
        "allocation_edits",
        "field IN ('final_lbs', 'note', 'status')",
    )
    op.create_index(
        "ix_allocation_edits_allocation_id", "allocation_edits", ["allocation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_allocation_edits_allocation_id", table_name="allocation_edits")
    op.drop_constraint(op.f("ck_allocation_edits_field_valid"), "allocation_edits", type_="check")
    op.drop_index("ix_allocations_lot_id", table_name="allocations")
    op.drop_constraint(
        op.f("uq_allocations_allocation_run_id_lot_id_pantry_id"), "allocations", type_="unique"
    )
    op.drop_constraint(op.f("ck_allocations_decision_fields"), "allocations", type_="check")
    op.drop_constraint(op.f("ck_allocations_reason_source_valid"), "allocations", type_="check")
    op.drop_column("allocations", "reason_source")
    for name in ("counts_nonneg", "delivery_within_week", "week_is_monday"):
        op.drop_constraint(op.f(f"ck_allocation_runs_{name}"), "allocation_runs", type_="check")
    for column in (
        "duration_ms", "output_tokens", "input_tokens", "reason_model_id", "shipped_lbs",
        "reasons_template", "reasons_ai", "lots_excluded", "lots_considered", "delivery_date",
        "week_start",
    ):  # fmt: skip
        op.drop_column("allocation_runs", column)
