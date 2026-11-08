# MGKK Monitoring Tool

See [System flow and presentation guide](./docs/system-flow.md) for the
architecture, end-to-end poll flow, MikroTik demo walkthrough, and talk track.

## Start the infrastructure

Copy `.env.example` to `.env`, then start the services from the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

`.env` also configures PostgreSQL (`POSTGRES_USER`, `POSTGRES_DB`,
`POSTGRES_PASSWORD`, `POSTGRES_PORT`). The containers reach it at
`postgres:5432`; host tools (Alembic, pytest, a local `uvicorn`) use
`DATABASE_URL`, which points at `localhost:$POSTGRES_PORT` (5433 by default).

The Compose stack includes the FastAPI API, a device poller worker,
PostgreSQL, Redis, Prometheus, and Grafana. The poller can check devices using
ICMP, SNMPv2c, or the MikroTik RouterOS REST API over HTTPS. The worker has
`NET_RAW` for ICMP. On Docker Desktop for Windows, additional routing or
bridging may be needed for the poller container to reach a lab subnet; verify
connectivity from inside that container. The API exposes `/health` and
`/metrics`.

Services are bound to localhost:

- API: <http://localhost:8000/health>
- Prometheus: <http://localhost:9090>
- Grafana: <http://localhost:3000> (credentials from `.env`)

The example credentials are for local development only. Change them before
using this stack outside a trusted local environment.

## Start the frontend

In a separate terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite development server proxies `/api` requests to the API on port 8000.
Run `npm run lint` and `npm run build` from `frontend` to check the frontend.

## Backend development with uv

The Python environment lives in `.venv` and is managed with
[uv](https://docs.astral.sh/uv/). uv is part of the dev dependency group, so
activating the venv makes the `uv` command available:

```powershell
.\.venv\Scripts\Activate.ps1
uv sync             # install dependencies from uv.lock
uv add <package>    # add a runtime dependency
uv add --dev <pkg>  # add a development dependency
uv run pytest
uv run ruff check .
uv run uvicorn app.main:app --app-dir backend --reload
```

Do not install packages with `pip`: `uv sync` removes anything that is not
listed in `uv.lock`.

## Inventory database

The `backend/app/models` and `backend/app/schemas` packages define the Phase 1
inventory (sites, devices, device groups) with SQLAlchemy 2.0 async models and
Pydantic v2 schemas. `backend/app/db/session.py` exposes the async engine,
`SessionLocal`, and the `get_session` FastAPI dependency.

Apply the schema to the Compose PostgreSQL (mapped on port 5433). The repository
`.env` is loaded automatically by Alembic, the API, and the test fixtures, so
you don't need to export `DATABASE_URL` by hand (real environment variables
still win):

```powershell
uv run alembic -c backend/alembic.ini upgrade head   # from the repository root
uv run alembic upgrade head                          # from backend/
```

Model tests need a disposable PostgreSQL database; they drop and recreate the
tables, so never point `TEST_DATABASE_URL` at real data. Create it once:

```powershell
docker compose exec -T postgres createdb -U mgkk mgkk_test
uv run pytest
```

## Inventory API

CRUD lives in `backend/app/crud/*.py` (data access) and
`backend/app/api/routes/*.py` (HTTP), and every router is mounted under `/api`
in `backend/app/main.py`. Interactive docs: <http://localhost:8000/docs>.

### Sites

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/sites?limit=50&offset=0` | Paginated list (`Page[SiteRead]`) |
| `GET` | `/api/sites/{site_id}` | One site, `404` if missing |
| `POST` | `/api/sites` | Create, `201`; duplicate `code` → `409` |
| `PATCH` | `/api/sites/{site_id}` | Partial update; duplicate `code` → `409` |
| `DELETE` | `/api/sites/{site_id}` | Delete, `204`; `409` while devices reference it |

### Devices

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/devices?site_id=&is_active=&device_type=&limit=50&offset=0` | Filtered, paginated list (`Page[DeviceRead]`) |
| `GET` | `/api/devices/{device_id}` | Detail with `site`, `groups`, `parent` |
| `POST` | `/api/devices` | Create, `201`; duplicate `name` → `409`; unknown `site_id`/`group_ids`/`parent_device_id` → `422` |
| `PATCH` | `/api/devices/{device_id}` | Partial update; `group_ids` replaces membership; own-parent → `422` |
| `DELETE` | `/api/devices/{device_id}` | Delete, `204`; children's `parent_device_id` becomes `NULL` |

`check_type` is `ping_only`, `snmp`, or `routeros_api`. SNMP and RouterOS API
checks require a `credential_profile_id` whose profile type matches the check.

### Device groups

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/device-groups?limit=50&offset=0` | Paginated list (`Page[DeviceGroupRead]`) |
| `GET` | `/api/device-groups/{group_id}` | One group, `404` if missing |
| `POST` | `/api/device-groups` | Create, `201`; duplicate `name` → `409` |
| `PATCH` | `/api/device-groups/{group_id}` | Partial update; duplicate `name` → `409` |
| `DELETE` | `/api/device-groups/{group_id}` | Delete, `204`; devices are kept |
| `GET` | `/api/device-groups/{group_id}/devices` | Members (`Page[DeviceRead]`) |
| `POST` | `/api/device-groups/{group_id}/devices` | Add members (`{"device_ids": [...]}`), `204`, idempotent |
| `DELETE` | `/api/device-groups/{group_id}/devices/{device_id}` | Remove one member, `204` |
| `GET` | `/api/credential-profiles` | List profiles without returning stored secrets |
| `POST` | `/api/credential-profiles` | Create an encrypted SNMP v2c or RouterOS API profile |
| `PATCH` | `/api/credential-profiles/{profile_id}` | Update profile metadata or replace its secret |
| `DELETE` | `/api/credential-profiles/{profile_id}` | Delete an unused profile; assigned profiles return `409` |

`PATCH` bodies use `exclude_unset`, so omitted fields are untouched. An
explicit `null` for a NOT NULL column returns `422`.

## MikroTik and protocol checks

Set a device's vendor to `mikrotik` and select its check type in the device
form. RouterOS API checks use the RouterOS REST endpoint
(`/rest/system/resource`) over HTTPS; SNMP checks currently use SNMPv2c and
read `sysUpTime`. These checks confirm reachability and authentication; they
do not yet collect full interface or system inventory.

Non-ICMP checks require a reusable credential profile. SNMP profiles contain a
read-only community string; RouterOS API profiles contain a read-only username
and password. Secrets are encrypted in PostgreSQL with Fernet. Generate a key
and put it in `.env` as `CREDENTIAL_ENCRYPTION_KEY` before starting Compose:

```powershell
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key backed up and private: the poller and API both need the same key
to use saved credentials, and changing it makes existing profile secrets
unreadable. RouterOS API profiles verify TLS certificates by default. For a
lab router using a self-signed certificate, you can explicitly disable
verification in the profile; prefer a trusted certificate outside a lab.
Credential profile API responses never contain the secret. The app does not
currently provide user authentication, so keep the API restricted to trusted
networks.

The Compose file does not create MikroTik CHR instances or a routed lab
network. Configure SNMP and `www-ssl` on each router, create a read-only
monitoring account, and ensure the poller container can reach the router's
management IP and selected service port.
