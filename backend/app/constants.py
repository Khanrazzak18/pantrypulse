"""Fixed reference data shared by the models, the migration and the data generator."""

# category = the food type; storage_type = the temperature (see docs/architecture.md).
CATEGORY_NAMES = (
    "produce",
    "dairy",
    "protein",
    "bakery",
    "frozen",
    "canned",
    "dry_goods",
    "beverages",
)
# `frozen` is only for frozen items that fit no other category (e.g. frozen meals),
# so it is not counted among the 3-7 day perishables.
PERISHABLE_CATEGORIES = frozenset({"produce", "dairy", "protein", "bakery"})

STORAGE_TYPES = ("ambient", "refrigerated", "frozen")
ROLES = ("coordinator", "pantry_manager", "admin")
DONOR_TYPES = ("grocery", "farm", "food_drive", "other")
DONATION_SOURCES = ("email", "pdf", "image", "text", "historical")
DONATION_STATUSES = ("pending_review", "confirmed", "rejected")
LOT_STATUSES = ("available", "depleted", "expired")
RUN_STATUSES = ("running", "completed", "failed")
RUN_KINDS = ("forward", "backtest")
ALLOCATION_RUN_STATUSES = ("draft", "completed")
ALLOCATION_STATUSES = ("proposed", "approved", "edited", "rejected")
REASON_SOURCES = ("ai", "template")
EDIT_FIELDS = ("final_lbs", "note", "status")
SUMMARY_STATUSES = ("draft", "approved")

# Six fictional counties around a notional region, with their centre points (lat, lon).
COUNTIES = {
    "Ashford": (40.30, -83.30),
    "Brookmere": (40.30, -82.70),
    "Cedar Vale": (40.00, -83.40),
    "Dunmore": (40.00, -82.60),
    "Elmhurst": (39.70, -83.30),
    "Fairhaven": (39.70, -82.70),
}

# The single warehouse, central to the six counties (lat, lon).
WAREHOUSE = (40.00, -83.00)
