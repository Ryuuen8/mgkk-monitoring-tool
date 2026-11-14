# Phase 2 telemetry verification

This procedure compares the app's rates with the cumulative counters exposed
by the lab `snmpd` target and MikroTik CHR. It is a manual integration check;
the automated tests use mocked SNMP and RouterOS responses. No live-device
comparison is implied until these steps have been run in the target lab.

## Prepare

1. Start the optional lab using [lab-setup.md](./lab-setup.md), apply database
   migrations, and configure one Generic SNMP device for the Linux `snmp-lab`
   agent and one MikroTik device for the CHR.
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

Grafana provisions **Generic Router/Switch Health** and **MikroTik Router
Health** from `deploy/grafana/dashboards/`. Confirm that dashboard traffic
and utilization series match the corresponding UI series over the same time
range and interface selection.
