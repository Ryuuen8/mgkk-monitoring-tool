# MGKK Monitoring Tool

See [System flow and presentation guide](./docs/system-flow.md) for the
architecture, end-to-end poll flow, MikroTik demo walkthrough, and talk track.
The frontend also has a **Guide** tab with an in-app walkthrough of each UI
screen and its controls.

For the optional isolated SNMP/RouterOS lab, see
[Lab setup](./docs/lab-setup.md). The UUID-based inventory and reachability
surface is available under `/api/v1`; the existing `/api` endpoints remain
available for compatibility.

Use the [Phase 2 telemetry verification guide](./docs/phase-2-verification.md)
to compare interface rates and utilization with lab Linux SNMP and MikroTik
CHR counters. The [Phase 3 alerting guide](./docs/phase-3-alerting.md) covers
Prometheus alert rules, Alertmanager routing and parent inhibition, maintenance
windows, syslog ingestion, and the authenticated live-events WebSocket.

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

The Compose stack includes the FastAPI API, a device poller worker, a syslog
receiver, PostgreSQL, Redis, Prometheus, Alertmanager, and Grafana. A one-shot
`migrate` service applies the Alembic schema before the API and worker start.
The poller can check devices using
ICMP, SNMPv2c/v3, the MikroTik RouterOS REST or binary API, or Cisco IOS-XE
RESTCONF. SNMP and RouterOS API checks collect system/interface telemetry.
MikroTik SNMP reports CPU and memory through its vendor MIB; generic SNMP uses
HOST-RESOURCES-MIB when the agent implements it and ENTITY-SENSOR-MIB for
temperature/voltage/fan readings. The Cisco collector adds CISCO-PROCESS-MIB,
CISCO-MEMORY-POOL-MIB, CISCO-ENVMON-MIB, CDP/LLDP topology, and stack-member
snapshots. Grafana dashboards are provisioned from
`deploy/`. The worker has `NET_RAW` for ICMP. On Docker Desktop for Windows,
additional routing or bridging may be needed for the poller container to reach
a lab subnet; verify connectivity from inside that container. The API exposes
`/health` and `/metrics`.

Services are bound to localhost:

- API: <http://localhost:8000/health>
- Prometheus: <http://localhost:9090>
- Alertmanager: <http://localhost:9093>
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
Run `npm run lint`, `npm test`, and `npm run build` from `frontend` to check
the frontend. With the API running, regenerate its TypeScript types with
`npm run generate:api`.

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

Compose applies the same migrations automatically through the `migrate`
service. CI runs `alembic upgrade head` plus `alembic check` against a
PostgreSQL 17 service, so model/schema drift fails the build.

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
| `GET` | `/api/devices/status` | Latest check status, latency, packet loss, and last-seen time for each device |
| `GET` | `/api/devices/{device_id}` | Detail with `site`, `groups`, `parent` |
| `GET` | `/api/devices/{device_id}/metrics?range_minutes=60&step_seconds=30` | Latency, availability, and packet-loss history; range is 5–1440 minutes |
| `GET` | `/api/devices/{device_id}/interfaces` | Discovered SNMP or RouterOS interface inventory and link speeds |
| `PATCH` | `/api/devices/{device_id}/interfaces/{interface_id}` | Set/clear a positive link-speed override in Mbps |
| `GET` | `/api/devices/{device_id}/interfaces/{interface_id}/metrics?range_hours=24&step_seconds=300` | Traffic, error, discard, and utilization samples; `range_hours` must be 24, 168, or 720 |
| `POST` | `/api/devices` | Create, `201`; duplicate `name` → `409`; unknown `site_id`/`group_ids`/`parent_device_id` → `422` |
| `PATCH` | `/api/devices/{device_id}` | Partial update; `group_ids` replaces membership; own-parent → `422` |
| `DELETE` | `/api/devices/{device_id}` | Delete, `204`; children's `parent_device_id` becomes `NULL` |

`PATCH` bodies use `exclude_unset`, so omitted fields are untouched. An
explicit `null` for a NOT NULL column returns `422`.

`check_type` is `ping_only`, `snmp`, `routeros_api`, or `restconf`. Devices also
select a `collector`: `generic_snmp` for standard SNMP, `mikrotik` for
RouterOS-specific collection, or `cisco` for Cisco IOS/IOS-XE/NX-OS. RouterOS
API checks require the MikroTik collector; RESTCONF checks require the Cisco
collector. SNMP and RouterOS API checks require a matching encrypted credential
profile; SNMP accepts either v2c or v3, and RESTCONF requires a Cisco RESTCONF
profile. Interface metrics have only `device`, `interface`, and `site` labels.

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

### Credential profiles

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/credential-profiles` | List profiles without returning stored secrets |
| `POST` | `/api/credential-profiles` | Create an encrypted SNMP v2c/v3, RouterOS API, Cisco RESTCONF, or Cisco SSH profile |
| `PATCH` | `/api/credential-profiles/{profile_id}` | Update profile metadata or replace its secret |
| `DELETE` | `/api/credential-profiles/{profile_id}` | Delete an unused profile; assigned profiles return `409` |

## Versioned inventory API

The versioned inventory API is available under `/api/v1`. Sites, groups, and
devices use UUIDs as their public identity; legacy `/api` routes keep integer
IDs.

| Method | Path | Description |
|---|---|---|
| `GET` / `POST` | `/api/v1/sites` | Paginated site list and site creation |
| `GET` / `PATCH` / `DELETE` | `/api/v1/sites/{site_id}` | Read, update, and delete a site |
| `GET` / `POST` | `/api/v1/groups` | Paginated group list and group creation |
| `GET` / `PATCH` / `DELETE` | `/api/v1/groups/{group_id}` | Read, update, and delete a group |
| `GET` / `POST` | `/api/v1/devices` | Filtered, paginated inventory and device creation |
| `GET` / `PATCH` / `DELETE` | `/api/v1/devices/{uuid}` | Read, update, and delete by stable UUID |
| `GET` | `/api/v1/devices/status` | Live reachability, latency (ms), and packet loss (%) for all devices |
| `GET` | `/api/v1/devices/{uuid}/status` | The same live status for one device |
| `GET` | `/api/v1/devices/{uuid}/metrics` | Prometheus range data for latency and packet loss |
| `GET` | `/api/v1/devices/{uuid}/interfaces` | Discovered interfaces and reported/manual speeds |
| `GET` | `/api/v1/devices/{uuid}/neighbors` | Discovered CDP/LLDP/RouterOS adjacencies stored in PostgreSQL |
| `PATCH` | `/api/v1/devices/{uuid}/interfaces/{interface_id}` | Set or clear an interface speed override |
| `GET` | `/api/v1/devices/{uuid}/interfaces/metrics` | Batched interface traffic, errors, discards, and utilization |
| `GET` | `/api/v1/devices/{uuid}/interfaces/{interface_id}/metrics` | One interface's traffic, errors, discards, and utilization |

The v1 device contract uses `ip_address`, optional unique `mac_address`,
`collector` (`generic_snmp`, `mikrotik`, or `cisco`), optional `os_family`
(`routeros`, `ios`, `iosxe`, `nxos`, or `linux`), and UUID parent/device IDs.
List endpoints accept `q` (name, hostname, vendor, model, or management IP),
`limit`/`offset`, plus `collector`, `os_family`, `site_id`, `group_id`,
`vendor`, `active`, and `check_type` filters. Parent links reject self-parents
and multi-device cycles with `422`.

The database UUID is the stable public identity; integer foreign keys remain
internally to preserve compatibility with the existing inventory API. Run the
Alembic migrations through revision `0012` before using this API. Reachability
gauges use the low-cardinality `device`, `site`, and `device_id` labels, where
`device_id` is the stable UUID; metrics queries select on that label. The worker
exports reachability, CPU/memory, temperature/voltage, fan/power-supply status,
interface counters, interface utilization, and a low-cardinality neighbor count;
neighbor identities stay in PostgreSQL.

## Vendor collectors and protocol checks

Choose the collector explicitly in the device form. Generic SNMP, MikroTik
SNMP, and Cisco SNMP share the same system and IF-MIB interface polling path,
including the 64-bit `ifHCInOctets`/`ifHCOutOctets` counters and `ifHighSpeed`;
MikroTik adds vendor CPU, memory, disk, temperature, and voltage metrics. Generic
CPU and memory use HOST-RESOURCES-MIB when the agent implements it. Generic
environmental polling uses ENTITY-SENSOR-MIB; Cisco EnvMon fan and power-supply
state is collected only by the Cisco collector.

The Cisco collector keeps every Cisco Enterprise OID under
`backend/app/collectors/cisco/mibs.py`. It reads CISCO-PROCESS-MIB CPU,
CISCO-MEMORY-POOL-MIB memory, CISCO-ENVMON-MIB environment state,
CISCO-STACKWISE-MIB members, and CISCO-CDP-MIB adjacencies, while LLDP and
standard health reuse the shared generic SNMP helpers. Cisco devices can use
SNMP (the default) or an optional IOS-XE RESTCONF check type. Stack members and
discovered neighbors are dynamic data: they are stored in PostgreSQL, while
Prometheus receives only aggregate counts.

Every collector implements the same four operations: `collect_system`,
`collect_interfaces`, `collect_health`, and `discover_neighbors`. Prometheus
metric names and labels (`device`, `interface`, `site`) are identical across
collectors. IP addresses, MAC addresses, hostnames, routes, VLANs, VRFs, and
neighbor identities never become labels.

The MikroTik collector supports RouterOS REST on v7.1+ and falls back to the
binary API-SSL service on port 8729 for v6 devices. To use the unencrypted
binary API on port 8728, set that port explicitly in the credential profile.
It reads system resources/health, interface counters, DHCP lease and ARP
totals, wireless registration summaries, and `ip/neighbor` adjacencies.
DHCP/ARP values are counts; wireless metrics are aggregated by interface.
Client addresses, MACs, hostnames, and neighbor identifiers are never stored
as metric labels. Interface octet/error/discard values are Prometheus counters;
the UI graphs `rate()` results and speed-normalized utilization over 24 hours,
7 days, or 30 days. Counter snapshots persist between polls to handle resets.

Non-ICMP checks require a reusable credential profile. SNMP profiles contain a
read-only community string or SNMPv3 username, SHA/SHA-256 authentication
passphrase, and optional AES-128 privacy passphrase. RouterOS API profiles
contain a read-only username and password. Cisco RESTCONF and Cisco SSH profiles
contain a monitoring username and password; RESTCONF uses HTTPS on port 443 by
default. All secrets are encrypted in PostgreSQL with Fernet. Generate a key
and put it in `.env` as `ENCRYPTION_KEY` before starting Compose:

```powershell
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep the key backed up and private: the poller and API both need the same key
to use saved credentials, and changing it makes existing profile secrets
unreadable. RouterOS API profiles verify TLS certificates by default. For a
lab router using a self-signed certificate, you can explicitly disable
verification in the profile; prefer a trusted certificate outside a lab.
RouterOS v6 requires the binary API-SSL service (8729) for automatic fallback;
the unencrypted API service (8728) can be selected explicitly in the profile.
RouterOS v7.1+ can use the HTTPS REST service.
Credential profile API responses never contain the secret. The app does not
currently provide user authentication, so keep the API restricted to trusted
networks.

The Compose file does not create MikroTik CHR instances or a routed lab
network. Configure SNMP and/or the RouterOS API service on each router, create
a read-only monitoring account, and ensure the poller container can reach the
router's management IP and selected service port.

## Alerting, syslog, and live updates

Prometheus evaluates the rules in `deploy/prometheus/alerts.yml` and forwards
alerts to Alertmanager, which routes critical alerts to email and Slack and
posts every event to `POST /api/v1/alerts/webhook`. Alert history,
acknowledgements, maintenance windows, Alertmanager silences, and critical
syslog messages are exposed under `/api/v1` and shown in the **Alerts** tab.
Parent-down alerts suppress downstream devices through the low-cardinality
`device_parent_info` metric and `parent_device_id` inhibition.

The syslog receiver listens on UDP and TCP 5514. The worker, webhook, and syslog
receiver publish state changes to Redis; the authenticated
`/api/v1/ws/events` WebSocket streams them to the React UI for live status
badges and alert/syslog refreshes. Configure the behavior in `.env`:

| Variable | Purpose |
|---|---|
| `ALERTMANAGER_URL` | Alertmanager base URL used for silence management |
| `WS_AUTH_TOKEN` | Required WebSocket token; leave unset only on a trusted local network |
| `SMTP_SMARTHOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Alert email relay |
| `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` | Alert email sender and recipients |
| `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL` | Optional Slack notifications |
| `ALERT_WEBHOOK_URL` | Alertmanager webhook target (defaults to the API container) |
| `SYSLOG_PORT`, `SYSLOG_MIN_SEVERITY` | Syslog listen port and retention threshold |

See the [Phase 3 alerting guide](./docs/phase-3-alerting.md) for rule details,
inhibition mechanics, API examples, and MikroTik/Cisco syslog configuration.
