# Mshauri | Clinic Booking System

FastAPI · PostgreSQL · Keycloak · Docker · GitHub Actions

## What it does

- Returns available 30-minute appointment slots by doctor and date.
- Books, cancels, and reschedules appointments.
- Prevents double-booking under concurrent load (database-enforced).
- Enforces doctor working hours and per-doctor schedule exceptions.
- Authenticates via Keycloak (OIDC, Authorization Code + PKCE).
- Authorises by role (`patient`, `doctor`, `admin`) and granular permissions.

## Design decisions and trade-offs

**Modular monolith, not microservices.** The clinic is small. A monolith is simpler to deploy, test, and reason about at this scale. The `routers/` → `services/` → `repositories/` layering keeps the code modular enough to split later if needed.

**PostgreSQL partial unique index as the concurrency lock.** A partial unique index on `(doctor_id, start_at) WHERE status = 'booked'` is the single source of truth for double-booking prevention. It beats application-level locks (which don't survive crashes) and advisory locks (which require careful lifetime management). Cancelled rows don't hold the slot; no Redis or external lock service is required.

**Slot-swap deadlock retry.** Two concurrent reschedules that swap slots can deadlock at the database level (`40P01`). The service catches that error, retries the transaction once, and returns `409 SLOT_TAKEN` on a second failure — no 500 errors.

**Keycloak over a simple JWT library.** Keycloak handles brute-force protection, key rotation, and the realm-as-code export (`keycloak/realm-clinic.json`). The API performs RS256 validation with a JWKS cache (rate-limited refetch on unknown `kid`); it fails closed with 503 if Keycloak is unreachable but keys are not cached.

**UTC storage, clinic-local display.** All datetimes are stored in UTC. The API converts to/from the configured clinic timezone (`Africa/Nairobi`, +03:00) on the boundary. DST-safe: working windows are expressed in local wall time and converted to UTC before slot generation.

### Data model (simplified)

```
doctors ──< doctor_schedules   (recurring weekly windows)
        ──< schedule_exceptions (leave / closures)
        ──< appointments >── patients
```

`appointments` has a `status` column (`booked` | `cancelled`). The partial unique index ensures at most one `booked` row per `(doctor_id, start_at)`.

## Running locally

**Prerequisites:** Docker, Python 3.12, `pip`.

```bash
# 1. Start Postgres and Keycloak
docker compose up -d --wait db keycloak

# 2. Install Python dependencies
pip install -e ".[dev]"

# 3. Copy and review environment variables
cp .env.example .env          # edit if your ports differ

# 4. Apply migrations and load seed data
alembic upgrade head
python scripts/seed.py

# 5. Start the API (reload on file changes)
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000`. Swagger UI (with Keycloak login) is at `http://localhost:8000/docs` when `DOCS_ENABLED=true`.

**Default Keycloak accounts** (realm `clinic`, all dev-only credentials):

| Username | Password | Role | Permissions |
|---|---|---|---|
| `patient1` | `demo-patient1` | patient | — |
| `patient2` | `demo-patient2` | patient | — |
| `doctor1` | `demo-doctor1` | doctor | — |
| `doctor2` | `demo-doctor2` | doctor | — |
| `admin_full` | `demo-admin_full` | admin | book\_for\_patient, manage\_any, view\_any |
| `admin_view_only` | `demo-admin_view_only` | admin | view\_any |

Keycloak admin console: `http://localhost:8080` — username `admin`, password `admin`.

**Run the full test suite** (requires a running Postgres — the `db` service is enough):

```bash
make check          # lint + type-check + tests
pytest              # tests only
pytest tests/unit   # fast unit tests, no DB needed
```

## CI/CD

**GitHub Actions** (`.github/workflows/ci.yml`) runs on every pull request and on push to `main`:

1. **checks** — ruff lint, ruff format, mypy --strict, pytest (against a real Postgres service container).
2. **docker** — builds the production image and smoke-tests `GET /health` inside a running container.

The `docker` job only runs after `checks` passes. Concurrent runs on the same ref are cancelled to save runner minutes.

Deployment to OpenStack (Phase D) uses a pull-based approach: the VM polls a container registry and restarts the service via a systemd unit.

## Technology

- Python 3.12 and FastAPI (async, Pydantic v2)
- PostgreSQL 16 and SQLAlchemy 2 (asyncpg)
- Alembic migrations
- Keycloak 26 with OpenID Connect
- Pytest, pytest-asyncio, httpx
- Docker and Docker Compose
- GitHub Actions