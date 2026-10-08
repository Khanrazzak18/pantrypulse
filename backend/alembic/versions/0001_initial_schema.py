"""initial schema: every table in the CLAUDE.md data model, plus weekly_context

Also inserts the 8 fixed food categories, which are reference data rather than seed data.

Revision ID: 0001
Revises:
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# (name, perishable). `frozen` is only for frozen items that fit no other category.
CATEGORIES = [
    ("produce", True),
    ("dairy", True),
    ("protein", True),
    ("bakery", True),
    ("frozen", False),
    ("canned", False),
    ("dry_goods", False),
    ("beverages", False),
]


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("perishable", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "name IN ('produce', 'dairy', 'protein', 'bakery', 'frozen', 'canned', 'dry_goods', 'beverages')",
            name=op.f("ck_categories_name_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("name", name=op.f("uq_categories_name")),
    )
    op.create_table(
        "donors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("donor_type", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "donor_type IN ('grocery', 'farm', 'food_drive', 'other')",
            name=op.f("ck_donors_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_donors")),
        sa.UniqueConstraint("name", name=op.f("uq_donors_name")),
    )
    op.create_table(
        "pantries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("county", sa.String(length=40), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("cold_capacity_lbs", sa.Integer(), nullable=False),
        sa.Column("dry_capacity_lbs", sa.Integer(), nullable=False),
        sa.Column("baseline_households", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "county IN ('Ashford', 'Brookmere', 'Cedar Vale', 'Dunmore', 'Elmhurst', 'Fairhaven')",
            name=op.f("ck_pantries_county_valid"),
        ),
        sa.CheckConstraint("baseline_households > 0", name=op.f("ck_pantries_households_positive")),
        sa.CheckConstraint("cold_capacity_lbs >= 0", name=op.f("ck_pantries_cold_capacity_nonneg")),
        sa.CheckConstraint("dry_capacity_lbs >= 0", name=op.f("ck_pantries_dry_capacity_nonneg")),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name=op.f("ck_pantries_latitude_range")),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180", name=op.f("ck_pantries_longitude_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pantries")),
        sa.UniqueConstraint("name", name=op.f("uq_pantries_name")),
    )
    op.create_table(
        "weekly_context",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("county", sa.String(length=40), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("avg_temp_f", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("precip_in", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("school_holiday", sa.Boolean(), nullable=False),
        sa.Column("benefit_week", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "county IN ('Ashford', 'Brookmere', 'Cedar Vale', 'Dunmore', 'Elmhurst', 'Fairhaven')",
            name=op.f("ck_weekly_context_county_valid"),
        ),
        sa.CheckConstraint(
            "extract(isodow from week_start) = 1", name=op.f("ck_weekly_context_week_is_monday")
        ),
        sa.CheckConstraint("precip_in >= 0", name=op.f("ck_weekly_context_precip_nonneg")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weekly_context")),
        sa.UniqueConstraint(
            "county", "week_start", name=op.f("uq_weekly_context_county_week_start")
        ),
    )
    op.create_table(
        "distributions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pantry_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("households", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "extract(isodow from week_start) = 1", name=op.f("ck_distributions_week_is_monday")
        ),
        sa.CheckConstraint("households >= 0", name=op.f("ck_distributions_households_nonneg")),
        sa.CheckConstraint("lbs >= 0", name=op.f("ck_distributions_lbs_nonneg")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_distributions_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pantry_id"],
            ["pantries.id"],
            name=op.f("fk_distributions_pantry_id_pantries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_distributions")),
        sa.UniqueConstraint(
            "pantry_id",
            "category_id",
            "week_start",
            name=op.f("uq_distributions_pantry_id_category_id_week_start"),
        ),
    )
    op.create_index("ix_distributions_week_start", "distributions", ["week_start"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("pantry_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(role = 'pantry_manager') = (pantry_id IS NOT NULL)",
            name=op.f("ck_users_pantry_only_for_managers"),
        ),
        sa.CheckConstraint(
            "role IN ('coordinator', 'pantry_manager', 'admin')", name=op.f("ck_users_role_valid")
        ),
        sa.ForeignKeyConstraint(
            ["pantry_id"],
            ["pantries.id"],
            name=op.f("fk_users_pantry_id_pantries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "donations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("donor_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("file_key", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("raw_llm_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('email', 'pdf', 'image', 'text', 'historical')",
            name=op.f("ck_donations_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'confirmed', 'rejected')",
            name=op.f("ck_donations_status_valid"),
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name=op.f("ck_donations_latency_nonneg")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_donations_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["donor_id"],
            ["donors.id"],
            name=op.f("fk_donations_donor_id_donors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_donations")),
    )
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(length=60), nullable=False),
        sa.Column("wape_lightgbm", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("wape_baseline", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("train_start", sa.Date(), nullable=False),
        sa.Column("train_end", sa.Date(), nullable=False),
        sa.Column("horizon_week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_forecast_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "extract(isodow from horizon_week_start) = 1",
            name=op.f("ck_forecast_runs_horizon_is_monday"),
        ),
        sa.CheckConstraint(
            "train_start <= train_end", name=op.f("ck_forecast_runs_train_window_ordered")
        ),
        sa.CheckConstraint(
            "wape_baseline IS NULL OR wape_baseline >= 0",
            name=op.f("ck_forecast_runs_wape_base_nonneg"),
        ),
        sa.CheckConstraint(
            "wape_lightgbm IS NULL OR wape_lightgbm >= 0",
            name=op.f("ck_forecast_runs_wape_lgbm_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_forecast_runs_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecast_runs")),
    )
    op.create_table(
        "monthly_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("aggregates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ai_draft", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model_id", sa.String(length=120), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL AND final_text IS NOT NULL)",
            name=op.f("ck_monthly_summaries_approval_complete"),
        ),
        sa.CheckConstraint(
            "status = 'approved' OR (approved_by IS NULL AND approved_at IS NULL)",
            name=op.f("ck_monthly_summaries_draft_not_approved"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved')", name=op.f("ck_monthly_summaries_status_valid")
        ),
        sa.CheckConstraint(
            "extract(day from month) = 1", name=op.f("ck_monthly_summaries_month_is_first_day")
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_monthly_summaries_approved_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_monthly_summaries")),
        sa.UniqueConstraint("month", name=op.f("uq_monthly_summaries_month")),
    )
    op.create_table(
        "shortage_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pantry_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("severity", sa.SmallInteger(), nullable=False),
        sa.Column("households_turned_away", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reported_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "extract(isodow from week_start) = 1", name=op.f("ck_shortage_reports_week_is_monday")
        ),
        sa.CheckConstraint(
            "households_turned_away >= 0", name=op.f("ck_shortage_reports_turned_away_nonneg")
        ),
        sa.CheckConstraint(
            "severity BETWEEN 1 AND 3", name=op.f("ck_shortage_reports_severity_range")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_shortage_reports_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pantry_id"],
            ["pantries.id"],
            name=op.f("fk_shortage_reports_pantry_id_pantries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"],
            ["users.id"],
            name=op.f("fk_shortage_reports_reported_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shortage_reports")),
        sa.UniqueConstraint(
            "pantry_id",
            "category_id",
            "week_start",
            name=op.f("uq_shortage_reports_pantry_id_category_id_week_start"),
        ),
    )
    op.create_index(
        "ix_shortage_reports_week_start", "shortage_reports", ["week_start"], unique=False
    )
    op.create_table(
        "allocation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_run_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'completed')", name=op.f("ck_allocation_runs_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_allocation_runs_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            ["forecast_runs.id"],
            name=op.f("fk_allocation_runs_forecast_run_id_forecast_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allocation_runs")),
    )
    op.create_table(
        "donation_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("donation_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("estimated_weight_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("storage_type", sa.String(length=20), nullable=False),
        sa.Column(
            "confidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("edited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "storage_type IN ('ambient', 'refrigerated', 'frozen')",
            name=op.f("ck_donation_items_storage_valid"),
        ),
        sa.CheckConstraint(
            "estimated_weight_lbs > 0", name=op.f("ck_donation_items_weight_positive")
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_donation_items_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_donation_items_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["donation_id"],
            ["donations.id"],
            name=op.f("fk_donation_items_donation_id_donations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_donation_items")),
    )
    op.create_index(
        "ix_donation_items_donation_id", "donation_items", ["donation_id"], unique=False
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("forecast_run_id", sa.Integer(), nullable=False),
        sa.Column("pantry_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("p10_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("p50_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("p90_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("baseline_lbs", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.CheckConstraint(
            "baseline_lbs IS NULL OR baseline_lbs >= 0", name=op.f("ck_forecasts_baseline_nonneg")
        ),
        sa.CheckConstraint(
            "extract(isodow from week_start) = 1", name=op.f("ck_forecasts_week_is_monday")
        ),
        sa.CheckConstraint(
            "p10_lbs <= p50_lbs AND p50_lbs <= p90_lbs", name=op.f("ck_forecasts_quantiles_ordered")
        ),
        sa.CheckConstraint("p10_lbs >= 0", name=op.f("ck_forecasts_p10_nonneg")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_forecasts_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            ["forecast_runs.id"],
            name=op.f("fk_forecasts_forecast_run_id_forecast_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pantry_id"],
            ["pantries.id"],
            name=op.f("fk_forecasts_pantry_id_pantries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forecasts")),
        sa.UniqueConstraint(
            "forecast_run_id",
            "pantry_id",
            "category_id",
            "week_start",
            name=op.f("uq_forecasts_forecast_run_id_pantry_id_category_id_week_start"),
        ),
    )
    op.create_table(
        "inventory_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("donation_item_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("storage_type", sa.String(length=20), nullable=False),
        sa.Column("received_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("remaining_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("expired_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "status IN ('available', 'depleted', 'expired')",
            name=op.f("ck_inventory_lots_status_valid"),
        ),
        sa.CheckConstraint(
            "storage_type IN ('ambient', 'refrigerated', 'frozen')",
            name=op.f("ck_inventory_lots_storage_valid"),
        ),
        sa.CheckConstraint("expired_lbs >= 0", name=op.f("ck_inventory_lots_expired_nonneg")),
        sa.CheckConstraint("received_lbs > 0", name=op.f("ck_inventory_lots_received_positive")),
        sa.CheckConstraint(
            "remaining_lbs + expired_lbs <= received_lbs", name=op.f("ck_inventory_lots_lbs_add_up")
        ),
        sa.CheckConstraint("remaining_lbs >= 0", name=op.f("ck_inventory_lots_remaining_nonneg")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_inventory_lots_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["donation_item_id"],
            ["donation_items.id"],
            name=op.f("fk_inventory_lots_donation_item_id_donation_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_lots")),
    )
    op.create_index(
        "ix_inventory_lots_expiry_date", "inventory_lots", ["expiry_date"], unique=False
    )
    op.create_index(
        "ix_inventory_lots_received_date", "inventory_lots", ["received_date"], unique=False
    )
    op.create_table(
        "allocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allocation_run_id", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Integer(), nullable=False),
        sa.Column("pantry_id", sa.Integer(), nullable=False),
        sa.Column("recommended_lbs", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("final_lbs", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "(status = 'proposed') = (decided_at IS NULL)",
            name=op.f("ck_allocations_decided_at_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'proposed') = (decided_by IS NULL)",
            name=op.f("ck_allocations_decider_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'edited', 'rejected')",
            name=op.f("ck_allocations_status_valid"),
        ),
        sa.CheckConstraint(
            "final_lbs IS NULL OR final_lbs >= 0", name=op.f("ck_allocations_final_nonneg")
        ),
        sa.CheckConstraint("recommended_lbs > 0", name=op.f("ck_allocations_recommended_positive")),
        sa.ForeignKeyConstraint(
            ["allocation_run_id"],
            ["allocation_runs.id"],
            name=op.f("fk_allocations_allocation_run_id_allocation_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_allocations_decided_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["inventory_lots.id"],
            name=op.f("fk_allocations_lot_id_inventory_lots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pantry_id"],
            ["pantries.id"],
            name=op.f("fk_allocations_pantry_id_pantries"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allocations")),
    )
    op.create_index(
        "ix_allocations_allocation_run_id", "allocations", ["allocation_run_id"], unique=False
    )
    op.create_index("ix_allocations_pantry_id", "allocations", ["pantry_id"], unique=False)
    op.create_table(
        "allocation_edits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("allocation_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["allocations.id"],
            name=op.f("fk_allocation_edits_allocation_id_allocations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_allocation_edits_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_allocation_edits")),
    )

    categories = sa.table(
        "categories", sa.column("name", sa.String), sa.column("perishable", sa.Boolean)
    )
    op.bulk_insert(categories, [{"name": n, "perishable": p} for n, p in CATEGORIES])


def downgrade() -> None:
    op.drop_table("allocation_edits")
    op.drop_index("ix_allocations_pantry_id", table_name="allocations")
    op.drop_index("ix_allocations_allocation_run_id", table_name="allocations")
    op.drop_table("allocations")
    op.drop_index("ix_inventory_lots_received_date", table_name="inventory_lots")
    op.drop_index("ix_inventory_lots_expiry_date", table_name="inventory_lots")
    op.drop_table("inventory_lots")
    op.drop_table("forecasts")
    op.drop_index("ix_donation_items_donation_id", table_name="donation_items")
    op.drop_table("donation_items")
    op.drop_table("allocation_runs")
    op.drop_index("ix_shortage_reports_week_start", table_name="shortage_reports")
    op.drop_table("shortage_reports")
    op.drop_table("monthly_summaries")
    op.drop_table("forecast_runs")
    op.drop_table("donations")
    op.drop_table("users")
    op.drop_index("ix_distributions_week_start", table_name="distributions")
    op.drop_table("distributions")
    op.drop_table("weekly_context")
    op.drop_table("pantries")
    op.drop_table("donors")
    op.drop_table("categories")
