"""Write the API's OpenAPI document where the frontend's type generator reads it.

Run via `make api-types`, which then regenerates frontend/src/lib/api/schema.d.ts.
"""

import json
from pathlib import Path

from app.main import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "frontend/src/lib/api/openapi.json"


def build_openapi() -> dict:
    app = create_app()
    try:
        return app.openapi()
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    OPENAPI_PATH.write_text(json.dumps(build_openapi(), indent=2) + "\n")
    print(f"wrote {OPENAPI_PATH}")
