# MGKK Monitoring System Flow

## Presentation overview

MGKK Monitoring is a small, database-driven network inventory and reachability
monitor. Operators register devices in the web UI, choose how each device
should be checked, and review status, system data, and interface telemetry. A
separate worker performs checks and SNMP collection, persists inventory
snapshots in PostgreSQL, and exposes metrics for Prometheus.

## Architecture at a glance

```mermaid
flowchart LR
    Operator[Operator]
    UI[React + TypeScript UI]
    API[FastAPI API]
    DB[(PostgreSQL inventory)]
    Worker[Device poller worker]
    Targets[Lab devices\nMikroTik CHR / SNMP devices]
    Syslog[Syslog receiver]
    Redis[(Redis Pub/Sub)]
    Prom[Prometheus]
    AM[Alertmanager]
    Ops[Email / Slack]
    Grafana[Grafana]

    Operator --> UI
    UI -->|REST /api| API
    UI <-->|/api/v1/ws/events| Redis
    API -->|inventory, profiles, alert history| DB
    Worker -->|device list and profiles| DB
    Worker -->|ICMP / SNMPv2c and v3 / RouterOS REST or binary API| Targets
    Worker -->|status, interface counters, rates, resources| Prom
    Worker -->|device_status / interface_status| Redis
    Targets -->|syslog UDP/TCP 5514| Syslog
    Syslog -->|critical events| DB
    Syslog -->|syslog_event| Redis
    API -->|alert_fired / alert_resolved| Redis
    Prom -->|alert rules| AM
    AM -->|webhook| API
    AM -->|email / Slack| Ops
    AM -->|silences| API
    API -->|instant and range queries| Prom
    Prom -->|scrape /metrics| API
    Prom -->|scrape worker /metrics| Worker
    Grafana --> Prom
```

The React development server proxies `/api` requests to FastAPI, including the
WebSocket upgrade. In Docker Compose, the API, worker, syslog receiver,
PostgreSQL, Redis, Prometheus, Alertmanager, and Grafana communicate over the
Compose network.

## End-to-end device flow

1. **Register inventory.** In the UI, an operator creates a site and adds a
   device with a stable inventory name, management IP, optional vendor/model
   metadata, and poll interval. The database row ID is the device identity;
   the IP is an editable address, not a unique identifier.
2. **Choose a check and collector.** Select Ping only, SNMP, RouterOS API, or
   RESTCONF, then choose the generic SNMP, MikroTik, or Cisco telemetry
   collector. RouterOS API checks require the MikroTik collector; RESTCONF
   checks require the Cisco collector.
3. **Protect credentials.** A profile stores an SNMP community, RouterOS
   username/password, or Cisco RESTCONF/SSH username/password. SNMPv3 profiles
   support SHA/SHA-256 authentication and optional AES-128 privacy. All secrets
   are encrypted using the configured `ENCRYPTION_KEY`; profile responses never
   return them.
4. **Discover poll work.** Every worker tick, the poller reads active devices
   and their check profiles from PostgreSQL. Each device is checked when its
   own poll interval has elapsed.
5. **Check the device.**
   - **Ping:** `icmplib` sends three ICMP echo requests, each with a 2-second
     timeout. The worker container is granted `NET_RAW`.
   - **SNMP:** every SNMP collector uses the same system identity, uptime, and
     IF-MIB interface path. Generic CPU/memory use HOST-RESOURCES-MIB when
     available and ENTITY-SENSOR-MIB for environmental readings; MikroTik adds
     vendor resource and health metrics.
   - **Cisco:** SNMP reads CISCO-PROCESS-MIB, CISCO-MEMORY-POOL-MIB,
     CISCO-ENVMON-MIB, CISCO-CDP-MIB, and CISCO-STACKWISE-MIB in addition to
     the shared IF-MIB/LLDP path. IOS-XE RESTCONF is an optional check type.
   - **RouterOS API:** the MikroTik collector uses REST on RouterOS v7.1+ and
     the binary API-SSL service on v6. Port 8728 can be explicitly selected for
     an unencrypted API connection. It collects system resources, interfaces,
     aggregate DHCP/ARP/wireless data, and `ip/neighbor` adjacencies. TLS
     verification is enabled by default.
6. **Persist topology and dynamic data.** Discovered CDP, LLDP, and RouterOS
   neighbors are upserted into `device_neighbors`; stack members, DHCP leases,
   ARP entries, and wireless summaries are stored in `device_snapshots`.
   Prometheus receives aggregate counters only, never neighbor identities.
7. **Publish results.** Device checks expose `device_up`, `ping_latency_seconds`,
   and `ping_packet_loss_ratio`. Interface octet/error/discard metrics are
   Prometheus counters: each poll adds the positive delta from the saved
   SNMP/API counter, accounting for a counter reset or wrap.
   Prometheus `rate()` is used for traffic and error charts. Interface metrics
   have only `device`, `interface`, and `site` labels. Link utilization is
   computed from the observed traffic delta and discovered or operator-overridden
   `ifHighSpeed`. The worker also updates last-seen and system/interface
   snapshots in PostgreSQL.
8. **Display status and history.** Prometheus scrapes the API and worker.
   The UI gets inventory from FastAPI and the latest per-device check status
   from `/api/v1/devices/status` (the legacy `/api/devices/status` remains
   available); the API queries Prometheus for status and
   historical latency, packet-loss, and interface telemetry. The device detail
   view also shows discovered system/interface data from PostgreSQL snapshots.

## Main components

| Component | Responsibility |
|---|---|
| React + TypeScript | Inventory, profile management, interface charts, live status badges, alert center, maintenance windows, and syslog feed |
| FastAPI | Validates inventory/profile/interface/alert requests and queries Prometheus |
| PostgreSQL | Stores inventory, encrypted credentials, snapshots, topology, alert history, maintenance windows, and critical syslog events |
| Poller worker | Runs checks, polls telemetry, persists snapshots/topology, exports metrics, and publishes state transitions |
| Syslog receiver | Listens on UDP/TCP 5514, matches devices by management IP, stores critical events, and publishes live syslog events |
| Prometheus | Scrapes API/worker metrics, evaluates alert rules, and retains time-series data |
| Alertmanager | Groups, inhibits, and routes alerts; manages silences; forwards events to the API webhook |
| Grafana | Included in Compose for dashboards using Prometheus as a data source |
| Redis | Pub/Sub bus that fans live events out to the authenticated WebSocket endpoint |

## Data and metric flow

```text
UI --device/profile CRUD--> FastAPI --inventory/profile data--> PostgreSQL
                                  ^                                |
                                  |                                | poll targets
                                  |                                v
UI <--status/chart response-- FastAPI <--Prometheus query-- Prometheus
                                                            ^
                                                            | scrape metrics
Lab device <--check-- Poller worker ------------------------+
```

The worker exports `device_up` (1/0), `ping_latency_seconds` (seconds),
`ping_packet_loss_ratio` (0-1), interface byte/error/discard counters,
link-utilization gauges, and CPU/memory gauges for devices exposing supported
MIB data. The API applies
`rate()` to true monotonic counters for interface history. Reachability series
carry `device`, `site`, and the stable `device_id` UUID; interface series use
only `device`, `interface`, and `site` labels. IP addresses and arbitrary tags
are never labels.

## Alerting, syslog, and live-event flow

1. **Evaluate rules.** Prometheus runs the reachability, interface, bandwidth,
   and hardware-health rules in `deploy/prometheus/alerts.yml`. Each rule
   reduces its input with `max by (device, site)` and joins
   `device_parent_info`, so alerts carry `device`, `site`, `device_id`,
   `parent_device`, and `parent_device_id` without high-cardinality labels.
2. **Inhibit and route.** Alertmanager groups alerts by alert name, device,
   site, and severity. A parent `DeviceDown` inhibits downstream devices and
   same-device interface/latency/resource alerts through `parent_device_id`.
   Critical alerts go to email and Slack; every alert is posted to the API
   webhook, including resolved notifications.
3. **Store and broadcast alerts.** The API upserts `alert_events` by
   fingerprint, applies open maintenance windows (storing suppressed alerts
   without broadcasting), and publishes `alert_fired` or `alert_resolved` to
   Redis.
4. **Ingest syslog.** The syslog receiver parses RFC 3164/5424, RouterOS, and
   Cisco messages, matches the source address to a device's management IP,
   stores critical events in `syslog_events`, and publishes `syslog_event`.
5. **Push to browsers.** `/api/v1/ws/events` subscribes to the `mgkk:events`
   channel, optionally checks `WS_AUTH_TOKEN`, filters by `site`/`device`, and
   streams events plus 25-second heartbeats. The UI updates status badges and
   refreshes the alert and syslog views.
6. **Silence planned work.** Maintenance windows create Alertmanager silences
   for a device, site code, or each group member. The DB window is also
   authoritative for webhook suppression, so a temporarily unreachable
   Alertmanager does not create alert noise in the app.

See [Phase 3: alerting, syslog, and live updates](./phase-3-alerting.md) for
rule expressions, inhibition details, API examples, and device syslog
configuration.

## MikroTik lab walkthrough

For a demo, prepare a reachable CHR/router and configure it before adding it to
the UI:

1. Configure SNMP and/or enable the RouterOS API. REST requires v7.1+ and
   `www-ssl`; automatic v6 fallback uses API-SSL on 8729.
2. Create a dedicated read-only SNMP community or RouterOS monitoring user.
   Restrict service access to the poller host/network where practical.
3. Set `ENCRYPTION_KEY` in `.env`, then start the app and apply the
   Alembic migration.
4. Open **Credentials** in the UI and add an SNMP v2c/v3 or RouterOS API profile.
   For a self-signed lab certificate, TLS verification can be disabled for
   that profile; use a trusted certificate outside a lab.
5. Open **Devices**, add a router, select the MikroTik collector and matching
   check type/profile, and save it.
6. Open device details to show system name/description, uptime, CPU/memory when
   exposed by the vendor or standard MIB, discovered interfaces, traffic/errors/discards, current and
   peak throughput, and 24-hour/7-day/30-day bandwidth history after Prometheus
   has collected samples. Set a link-speed override for virtual/tunnel
   interfaces when `ifHighSpeed` is missing or inaccurate.
7. Open Grafana's provisioned **Generic Router/Switch Health**,
   **MGKK Network Telemetry**, **MikroTik Router Health**, or
   **Cisco Router/Switch Health** dashboard to compare interface traffic,
   utilization, errors, resources, and environmental health.

Follow [Phase 2 telemetry verification](./phase-2-verification.md) to compare
the app's rates with cumulative Linux SNMP counters, CHR interface statistics,
and Cisco CLI/MIB output. The procedure is not a claim that a live lab
comparison was run.

For ICMP, the worker has `NET_RAW`. SNMP, RouterOS REST, and binary API use
UDP, HTTPS, and TCP respectively, so the poller container must also have IP
routing and firewall access to each lab device and service port. Docker Desktop on Windows may
require additional host/VM networking configuration; `docker compose up` alone
does not create a CHR or bridge a separate lab subnet.

## Demo talk track

The frontend **Guide** tab walks through Overview, Devices, device setup,
device details, credential profiles, and status troubleshooting. Use it as an
in-app orientation before the following demo:

1. Start on **Devices** and explain inventory identity versus the mutable
   management IP.
2. Show that each target has its own check type and polling interval.
3. Create or inspect a credential profile, noting that secrets are encrypted
   at rest and not returned to the UI.
4. Open a MikroTik device and explain that the worker independently checks it;
   the API remains responsive while polling runs.
5. Point out that Prometheus supplies the current status and the historical
   latency chart, while PostgreSQL holds the inventory and last-seen timestamp.
6. Mention the lab prerequisites: reachable management subnet, enabled
   RouterOS service, read-only credentials, and the encryption key.

## Current scope and caveats

- SNMP system and interface collection is implemented. MikroTik CPU/memory uses
  its vendor MIB; generic CPU/memory uses HOST-RESOURCES-MIB when available.
  Devices that do not implement these resource tables still provide system and
  interface telemetry, but their CPU/memory values remain unavailable.
- RouterOS REST is attempted first; failed REST access falls back to the
  RouterOS binary API-SSL on 8729. Port 8728 is available by explicit
  profile configuration. Wireless data is aggregated by interface;
  DHCP and ARP expose counts only, never client identity labels.
- Bandwidth history depends on Prometheus retention and is not backfilled before
  the poller first observes the interface.
- The Compose stack does not provision MikroTik CHR instances or SNMP test
  devices.
- Prometheus is the time-series source for device status and charts; the API's
  `/metrics` endpoint also reports API request metrics.
- Compose keeps Prometheus samples for 45 days so the 30-day bandwidth range is
  available with a retention buffer.
- Alert history starts when Alertmanager first forwards an event; the UI does
  not evaluate rules. Parent inhibition depends on the v1 `parent_device_id`
  inventory links and the Prometheus `device_id` → `parent_device_id` relabel.
- Syslog uses unauthenticated UDP/TCP; restrict port 5514 to the management
  network. The WebSocket is open unless `WS_AUTH_TOKEN` is set, and the API has
  no user authentication, so keep the whole stack on a trusted network.
- Maintenance-window silence creation is best effort. Suppression recorded in
  `alert_events` still applies when Alertmanager is unreachable, but external
  Alertmanager notifications may not be silenced until it recovers.
