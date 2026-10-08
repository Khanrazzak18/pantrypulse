"""forecast runs: forward vs backtest, coverage, model files, failure reason

A "forward" run trains once on all history and writes next week's forecast (fast, started from
the API). A "backtest" run scores 12 rolling origins (slow, started by `make backtest`) and
stores its accuracy on the run itself. Alembic does not detect CHECK constraints, so they are
written out here by hand.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("kind", sa.String(length=20), server_default="forward", nullable=False),
    )
    op.add_column("forecast_runs", sa.Column("coverage_p10_p90", sa.Numeric(5, 4), nullable=True))
    op.add_column("forecast_runs", sa.Column("backtest_start", sa.Date(), nullable=True))
    op.add_column("forecast_runs", sa.Column("model_key", sa.String(length=300), nullable=True))
    op.add_column("forecast_runs", sa.Column("error_message", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_forecast_runs_kind_valid"), "forecast_runs", "kind IN ('forward', 'backtest')"
    )
    op.create_check_constraint(
        op.f("ck_forecast_runs_coverage_range"),
        "forecast_runs",
        "coverage_p10_p90 IS NULL OR coverage_p10_p90 BETWEEN 0 AND 1",
    )
    op.create_check_constraint(
        op.f("ck_forecast_runs_backtest_start_is_monday"),
        "forecast_runs",
        "backtest_start IS NULL OR extract(isodow from backtest_start) = 1",
    )
    op.create_check_constraint(
        op.f("ck_forecast_runs_backtest_has_metrics"),
        "forecast_runs",
        "kind <> 'backtest' OR status <> 'completed' OR (wape_lightgbm IS NOT NULL "
        "AND wape_baseline IS NOT NULL AND coverage_p10_p90 IS NOT NULL "
        "AND backtest_start IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_forecast_runs_failed_has_reason"),
        "forecast_runs",
        "status <> 'failed' OR error_message IS NOT NULL",
    )


def downgrade() -> None:
    for name in (
        "failed_has_reason",
        "backtest_has_metrics",
        "backtest_start_is_monday",
        "coverage_range",
        "kind_valid",
    ):
        op.drop_constraint(op.f(f"ck_forecast_runs_{name}"), "forecast_runs", type_="check")
    op.drop_column("forecast_runs", "error_message")
    op.drop_column("forecast_runs", "model_key")
    op.drop_column("forecast_runs", "backtest_start")
    op.drop_column("forecast_runs", "coverage_p10_p90")
    op.drop_column("forecast_runs", "kind")
