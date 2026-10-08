from pydantic import BaseModel, ConfigDict


class PantryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    county: str
    latitude: float
    longitude: float
    cold_capacity_lbs: int
    dry_capacity_lbs: int
    baseline_households: int
