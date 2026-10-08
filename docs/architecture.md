# PantryPulse architecture

Local build of the system described in `spec-5.2.md`. `CLAUDE.md` is the build contract and wins
wherever it differs from the spec.

```
Browser ──> Next.js :3000 ── rewrites /api/* ──> FastAPI :8000 ──> Postgres 16 :5433 (Docker)
                                                     ├──> Amazon Bedrock (Stage 4)
                                                     └──> StorageBackend (LocalStorage now, S3 later)
```

- The browser talks to one origin. Next.js proxies `/api/*` to FastAPI, so there is no CORS setup
  and the auth cookie (Stage 3) is first-party.
- Ports and credentials are defined once in the root `.env`. The Makefile exports them to both
  processes; the API reads them through `app/config.py`, Next.js through `API_PORT`.
- One Postgres container holds two databases: `pantrypulse` and `pantrypulse_test`. Tests only
  ever touch the test database.
- The API is stateless: no in-process caches of database data.
- Every API error uses one envelope: `{"error": {"code", "message", "details"}}`.
- Logs are JSON, one line per request with `request_id`, `method`, `route`, `status` and
  `duration_ms`. The request id is returned in the `X-Request-ID` header.

## Decisions on points the spec leaves open

### Category versus storage type

`category` is the **food type**. `storage_type` carries the **temperature**.

- The 8 fixed categories are: produce, dairy, protein, bakery, frozen, canned, dry_goods, beverages.
- `storage_type` is one of: ambient, refrigerated, frozen.
- Frozen chicken is category `protein` with storage type `frozen`.
- The `frozen` category is used only for frozen items that fit no other category, such as frozen
  meals.
- Capacity checks (cold and dry storage per pantry) use `storage_type`, never `category`.

### Other definitions

- **Stockout:** a shortage report for a pantry, category and week.
- **Distance:** haversine distance between pantry and warehouse (or pantry-to-pantry) from
  latitude and longitude.
- **Warehouse:** one location, central to the six counties.
- **Weather and school holidays:** synthetic, generated with a fixed seed. The README says so.
- **Weekly refresh:** `POST /api/admin/jobs/weekly-refresh` requires the `admin` role.
- **Bedrock:** credentials come from the AWS CLI profile `pantrypulse` in `us-east-1`. The model ID
  is set in Stage 4. Tests always use a mocked provider and never call Bedrock; the running app
  always uses real Bedrock.
