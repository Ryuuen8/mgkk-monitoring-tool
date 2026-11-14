# Phase 2 telemetry verification

This procedure compares the app's rates with the cumulative counters exposed
by the lab `snmpd` target, MikroTik CHR, and Cisco IOS-XE device. It is a manual
integration check; the automated tests use mocked SNMP, RouterOS, and
RESTCONF responses. No live-device comparison is implied until these steps
have been run in the target lab.

## Prepare

1. Start the optional lab using [lab-setup.md](./lab-setup.md), apply database
   migrations, and configure one Generic SNMP device for the Linux `snmp-lab`
   agent, one MikroTik device for the CHR, and optionally a Cisco IOS-XE
   device for the Cisco checks.
2. Use a SNMP profile and a RouterOS profile created in the app. Do not put
   real or production credentials in shell history or terminal transcripts.
3. Ensure both devices have completed at least two polls. Select their
   interfaces in Device Detail, and wait at least five minutes for a complete
   rate window. The UI displays the last collected values and offers 24-hour,
   7-day, and 30-day history.

## Linux `snmpd` counter comparison

Run Net-SNMP's `snmpwalk`/`snmpget` on a trusted machine that can reach the lab
network. Obtain the `snmp-lab` container IP from Docker, then use the lab-only
v2c community value and numeric OIDs. Compose's `--env-file` does not export
variables into the current PowerShell session, so set
`LAB_SNMP_V2C_COMMUNITY` from the private local lab config without echoing or
recording the value in shared logs:

```powershell
docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' `
  (docker compose --env-file .env.lab -f compose.yaml -f deploy/docker-compose.lab.yml ps -q snmp-lab)
snmpwalk -v2c -c $env:LAB_SNMP_V2C_COMMUNITY -On <snmp-lab-ip> 1.3.6.1.2.1.2.2.1.2
snmpget -v2c -c $env:LAB_SNMP_V2C_COMMUNITY -On <snmp-lab-ip> `
  1.3.6.1.2.1.31.1.1.1.6.<ifIndex> 1.3.6.1.2.1.31.1.1.1.10.<ifIndex>
```

The walk maps interface descriptions to `ifIndex`; the GET returns inbound
and outbound 64-bit octet counters. Capture both values twice over the same
five-minute interval and calculate each direction as:

```text
Mbps = (counter_at_end - counter_at_start) * 8 / elapsed_seconds / 1,000,000
```

Compare this result with the UI's current in/out Mbps for the same interface,
and with Grafana's `rate(interface_in_bytes_total[5m]) * 8` and
`rate(interface_out_bytes_total[5m]) * 8` series. Poll timing and the
five-minute moving rate can cause small differences; verify the values trend
together over several intervals. The lab SNMP view includes IF-MIB, EtherLike,
HOST-RESOURCES, and ENTITY-SENSOR OIDs under the MIB-2 subtree.

## MikroTik CHR comparison

In the CHR terminal (or the WinBox Terminal), select the interface being
viewed and run:

```routeros
/interface monitor-traffic ether1 once
/interface print stats where name="ether1"
```

`monitor-traffic` reports an instantaneous rx/tx bit rate. The interface
statistics expose cumulative byte counters. For a like-for-like check, record
the cumulative rx/tx byte counters, wait five minutes, record them again, and
apply the same Mbps formula above. Compare those averages with the UI and the
Grafana 5-minute counter rates. Use `monitor-traffic` as an immediate
sanity-check that the direction and approximate rate agree. If a virtual,
bridge, VLAN, or tunnel interface advertises an incorrect speed, set its
manual speed override in Device Detail; utilization is rate divided by that
effective speed in bits per second.

## Cisco IOS-XE comparison

Use the Cisco lab device from [lab-setup.md](./lab-setup.md), or any IOS-XE
device with SNMP and, optionally, RESTCONF enabled. Confirm that the device
collects with the Cisco collector and SNMP profile, and that at least two polls
have completed.

On the device, compare the app's health values with:

```text
show processes cpu | include CPU utilization
show memory statistics
show environment all
show interfaces counters errors
show interfaces <interface> | include CRC|input errors|output errors|discards
```

The collector prefers CISCO-PROCESS-MIB `cpmCPUTotal5minRev`
(`1.3.6.1.4.1.9.9.109.1.1.1.1.8.<cpuIndex>`) over the 1-minute and 5-second
columns, and averages all reported CPU table rows (for example stack members).
Memory comes from CISCO-MEMORY-POOL-MIB used/free columns
(`1.3.6.1.4.1.9.9.48.1.1.1.5` and `.6`). Temperature, voltage, fan, and
power-supply state come from CISCO-ENVMON-MIB; compare them with
`show environment all`. Interface CRC/FCS counters come from the same
EtherLike-MIB walk used by the generic collector and should track
`show interfaces counters errors` over several intervals.

For a RESTCONF check type, compare the app with:

```text
GET /restconf/data/Cisco-IOS-XE-process-cpu-oper:cpu-usage/cpu-utilization
GET /restconf/data/Cisco-IOS-XE-interfaces-oper:interfaces/interface
GET /restconf/data/ietf-interfaces:interfaces-state
```

The collector reads the Cisco interfaces-oper model first and falls back to
`ietf-interfaces:interfaces-state` when the Cisco model is unavailable. CPU
uses the five-minute leaf when the device exposes it. Interface counters and
rates appear as `interface_*` metrics with the same labels as SNMP devices.

## API and dashboard spot checks

The interface history endpoint accepts only 24-hour, 7-day, and 30-day ranges:

```text
GET /api/v1/devices/{device_uuid}/interfaces/{interface_id}/metrics?range_hours=24&step_seconds=300
GET /api/v1/devices/{device_uuid}/interfaces/{interface_id}/metrics?range_hours=168&step_seconds=1800
GET /api/v1/devices/{device_uuid}/interfaces/{interface_id}/metrics?range_hours=720&step_seconds=3600
```

In Prometheus, query `interface_in_bytes_total`, `interface_out_bytes_total`,
`interface_in_utilization_percent`, `interface_out_utilization_percent`, and
`rate(interface_crc_errors_total[5m])`. Confirm every interface time series
uses only `device`, `interface`, and `site` labels. Operational snapshots
(DHCP leases, ARP entries, and wireless summaries) are PostgreSQL data and
must not appear as Prometheus labels.

Grafana provisions **Generic Router/Switch Health**, **MikroTik Router
Health**, and **Cisco Router/Switch Health** from
`deploy/grafana/dashboards/`. Confirm that dashboard traffic, utilization,
errors, CRC/FCS, CPU, memory, and environmental-health series match the
corresponding UI and device output over the same time range and interface
selection.
