"""`make refresh`: log in as the demo admin and call POST /api/admin/jobs/weekly-refresh.

Local convenience only. In production EventBridge would call the same endpoint with a service
credential. The password comes from DEMO_ADMIN_PASSWORD in .env and is never printed.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

from app.config import get_settings
from scripts.seed import DEMO_EMAILS


def main() -> int:
    port = os.environ.get("API_PORT")
    password = get_settings().demo_admin_password
    if not port or not password:
        print("API_PORT and DEMO_ADMIN_PASSWORD must be set in .env (run via make).")
        return 2
    base = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def post(path: str, body: dict | None = None, timeout: int = 60) -> dict:
        data = json.dumps(body).encode() if body is not None else b""
        request = urllib.request.Request(
            base + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)

    try:
        post("/api/auth/login", {"email": DEMO_EMAILS["admin"], "password": password}, timeout=10)
        out = post("/api/admin/jobs/weekly-refresh")
    except urllib.error.HTTPError as exc:
        try:
            error = json.load(exc)["error"]
            print(f"Refresh failed ({exc.code} {error['code']}): {error['message']}")
        except (ValueError, KeyError):
            print(f"Refresh failed with HTTP {exc.code}.")
        return 1
    except urllib.error.URLError:
        print(f"Could not reach the API at {base}. Is `make dev` running?")
        return 1
    for step in out["steps"]:
        print(f"  {step['name']:<11} {step['status']}  {step['seconds']} s")
    print(
        f"Week of {out['week_start']}: forecast run {out['forecast_run_id']}, allocation run "
        f"{out['allocation_run_id']} ({out['proposed_rows']} rows). Total {out['total_seconds']} s."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
