import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  formatCheckType,
  formatDeviceType,
  formatLatency,
  formatLoss,
  formatTimestamp,
  type DeviceDetail,
  type DeviceMetrics,
  type DeviceStatus,
  type InterfaceMetrics,
  type NetworkInterface,
} from "../api/client";
import LatencyChart from "./LatencyChart";

type DeviceDetailPageProps = {
  deviceId: number;
  onBack: () => void;
  onEdit: (id: number) => void;
};

const RANGES = [
  { label: "15 min", minutes: 15, step: 15 },
  { label: "1 hour", minutes: 60, step: 30 },
  { label: "6 hours", minutes: 360, step: 120 },
  { label: "24 hours", minutes: 1440, step: 300 },
];
const BANDWIDTH_RANGES = [
  { label: "24h", hours: 24, step: 300 },
  { label: "7d", hours: 168, step: 1800 },
  { label: "30d", hours: 720, step: 3600 },
] as const;

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function latest(values: { value: number }[]): number | null {
  return values.length === 0 ? null : values[values.length - 1].value;
}

function peak(values: { value: number }[]): number | null {
  return values.length === 0
    ? null
    : Math.max(...values.map((point) => point.value));
}

function formatMbps(value: number | null): string {
  return value == null ? "—" : `${(value / 1_000_000).toFixed(2)} Mbps`;
}

function DeviceDetailPage({ deviceId, onBack, onEdit }: DeviceDetailPageProps) {
  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [metrics, setMetrics] = useState<DeviceMetrics | null>(null);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [interfaces, setInterfaces] = useState<NetworkInterface[]>([]);
  const [selectedInterfaceId, setSelectedInterfaceId] = useState<number | null>(
    null,
  );
  const [interfaceMetrics, setInterfaceMetrics] =
    useState<InterfaceMetrics | null>(null);
  const [bandwidthHours, setBandwidthHours] = useState(24);
  const [bandwidthError, setBandwidthError] = useState<string | null>(null);
  const [rangeMinutes, setRangeMinutes] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const range = RANGES.find((item) => item.minutes === rangeMinutes) ?? RANGES[1];

    const load = async () => {
      const [deviceResponse, metricsResponse, statusResponse, interfacesResponse] = await Promise.all([
        api.GET("/api/devices/{device_id}", {
          params: { path: { device_id: deviceId } },
        }),
        api.GET("/api/devices/{device_id}/metrics", {
          params: {
            path: { device_id: deviceId },
            query: { range_minutes: range.minutes, step_seconds: range.step },
          },
        }),
        api.GET("/api/devices/status"),
        api.GET("/api/devices/{device_id}/interfaces", {
          params: { path: { device_id: deviceId } },
        }),
      ]);
      if (cancelled) return;

      if (deviceResponse.error) {
        setError(errorMessage(deviceResponse.error));
        setLoading(false);
        return;
      }
      setDevice(deviceResponse.data);
      setError(null);

      if (metricsResponse.error) {
        setChartError(errorMessage(metricsResponse.error));
      } else {
        setMetrics(metricsResponse.data);
        setChartError(null);
      }

      if (statusResponse.data) {
        setStatus(
          statusResponse.data.items.find((item) => item.device_id === deviceId) ??
            null,
        );
      }
      if (interfacesResponse.data) {
        setInterfaces(interfacesResponse.data);
        setSelectedInterfaceId((current) =>
          current != null &&
          interfacesResponse.data.some((item) => item.id === current)
            ? current
            : interfacesResponse.data[0]?.id ?? null,
        );
        setBandwidthError(null);
      } else if (interfacesResponse.error) {
        setBandwidthError(errorMessage(interfacesResponse.error));
      }
      setLoading(false);
    };

    void load();
    const timer = window.setInterval(() => void load(), 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [deviceId, rangeMinutes]);

  useEffect(() => {
    if (selectedInterfaceId == null) {
      setInterfaceMetrics(null);
      return;
    }
    let cancelled = false;
    const range =
      BANDWIDTH_RANGES.find((item) => item.hours === bandwidthHours) ??
      BANDWIDTH_RANGES[0];
    const load = async () => {
      const { data, error: responseError } = await api.GET(
        "/api/devices/{device_id}/interfaces/{interface_id}/metrics",
        {
          params: {
            path: { device_id: deviceId, interface_id: selectedInterfaceId },
            query: { range_hours: range.hours, step_seconds: range.step },
          },
        },
      );
      if (cancelled) return;
      if (responseError) {
        setBandwidthError(errorMessage(responseError));
      } else {
        setInterfaceMetrics(data);
        setBandwidthError(null);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [deviceId, selectedInterfaceId, bandwidthHours]);

  const updateLinkSpeed = async (item: NetworkInterface) => {
    const value = window.prompt(
      "Link speed override in Mbps. Leave blank to use the SNMP-reported speed.",
      item.link_speed_override_mbps?.toString() ?? "",
    );
    if (value === null) return;
    const speed = value.trim() === "" ? null : Number(value);
    if (
      speed !== null &&
      (!Number.isSafeInteger(speed) || speed <= 0)
    ) {
      setBandwidthError("Link speed must be a positive whole number of Mbps.");
      return;
    }
    const { data, error: responseError } = await api.PATCH(
      "/api/devices/{device_id}/interfaces/{interface_id}",
      {
        params: {
          path: { device_id: deviceId, interface_id: item.id },
        },
        body: { link_speed_override_mbps: speed },
      },
    );
    if (responseError) {
      setBandwidthError(errorMessage(responseError));
      return;
    }
    setInterfaces((current) =>
      current.map((row) => (row.id === item.id ? data : row)),
    );
    setBandwidthError(null);
  };

  if (loading && !device) {
    return <p className="muted">Loading device…</p>;
  }

  if (!device) {
    return (
      <section className="page-section">
        <p className="banner banner-error">{error ?? "Device not found."}</p>
        <button className="button" onClick={onBack}>
          Back to devices
        </button>
      </section>
    );
  }

  const latencyMs = metrics
    ? metrics.latency.map((point) => ({ t: point.t, value: point.value * 1000 }))
    : [];
  const uptimePercent = metrics
    ? average(metrics.uptime.map((point) => point.value))
    : null;
  const lossPercent = metrics
    ? average(metrics.packet_loss.map((point) => point.value))
    : null;

  const up = status?.up ?? null;
  const isPingCheck = !device.check_type || device.check_type === "ping_only";
  const statusText = up == null ? "No data" : up ? "Online" : "Offline";
  const statusClass = up == null ? "status-unknown" : up ? "status-online" : "status-offline";
  const bandwidthRangeLabel =
    BANDWIDTH_RANGES.find((range) => range.hours === bandwidthHours)?.label ??
    "24h";

  return (
    <section className="page-section" aria-labelledby="device-title">
      <div className="page-heading">
        <div>
          <button className="link-button back-link" onClick={onBack}>
            ← Back to devices
          </button>
          <p className="eyebrow">
            DEVICE <span> / </span> {device.site.code}
          </p>
          <h1 id="device-title">{device.name}</h1>
          <p className="subtitle">
            {formatDeviceType(device.device_type)} · {device.mgmt_ip}
            {device.hostname ? ` · ${device.hostname}` : ""}
          </p>
        </div>
        <div className="heading-actions">
          <span className={`status ${statusClass}`}>
            <span className="status-dot" />
            {statusText}
          </span>
          <button className="button" onClick={() => onEdit(device.id)}>
            Edit device
          </button>
        </div>
      </div>

      {error && <p className="banner banner-error">{error}</p>}

      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-label">Latency now</span>
          <strong className="stat-value">{formatLatency(status?.latency_ms)}</strong>
        </div>
        {isPingCheck && (
          <div className="stat-card">
            <span className="stat-label">Packet loss now</span>
            <strong className="stat-value">
              {formatLoss(status?.packet_loss)}
            </strong>
          </div>
        )}
        <div className="stat-card">
          <span className="stat-label">Uptime (range)</span>
          <strong className="stat-value">
            {uptimePercent == null ? "—" : `${(uptimePercent * 100).toFixed(1)}%`}
          </strong>
        </div>
        {isPingCheck && (
          <div className="stat-card">
            <span className="stat-label">Avg loss (range)</span>
            <strong className="stat-value">
              {lossPercent == null ? "—" : `${(lossPercent * 100).toFixed(1)}%`}
            </strong>
          </div>
        )}
        <div className="stat-card">
          <span className="stat-label">Last seen</span>
          <strong className="stat-value stat-small">
            {formatTimestamp(device.last_seen_at ?? status?.last_seen_at)}
          </strong>
        </div>
        <div className="stat-card">
          <span className="stat-label">Poll interval</span>
          <strong className="stat-value">{device.poll_interval_seconds}s</strong>
        </div>
      </div>

      <section className="chart-card" aria-labelledby="chart-title">
        <div className="chart-heading">
          <div>
            <h2 id="chart-title">Check latency</h2>
            <p className="muted">
              {metrics ? `${metrics.latency.length} samples` : "No samples"} ·
              source: Prometheus · {formatCheckType(device.check_type)}
            </p>
          </div>
          <div className="range-picker" role="group" aria-label="Chart range">
            {RANGES.map((range) => (
              <button
                key={range.minutes}
                className={`range-button ${
                  range.minutes === rangeMinutes ? "range-active" : ""
                }`}
                onClick={() => setRangeMinutes(range.minutes)}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>

        {chartError && <p className="banner banner-error">{chartError}</p>}
        <LatencyChart points={latencyMs} />
      </section>

      <section className="info-card" aria-labelledby="info-title">
        <h2 id="info-title">Inventory details</h2>
        <dl className="detail-list">
          <div>
            <dt>Site</dt>
            <dd>
              {device.site.name} ({device.site.code})
            </dd>
          </div>
          <div>
            <dt>Management IP</dt>
            <dd className="mono">{device.mgmt_ip}</dd>
          </div>
          <div>
            <dt>Type</dt>
            <dd>{formatDeviceType(device.device_type)}</dd>
          </div>
          <div>
            <dt>Vendor / model</dt>
            <dd>
              {[device.vendor, device.model].filter(Boolean).join(" / ") || "—"}
            </dd>
          </div>
          <div>
            <dt>OS version</dt>
            <dd>{device.os_version ?? "—"}</dd>
          </div>
          <div>
            <dt>SNMP system name</dt>
            <dd>{device.snmp_system_name ?? "—"}</dd>
          </div>
          <div>
            <dt>System description</dt>
            <dd>{device.snmp_system_description ?? "—"}</dd>
          </div>
          <div>
            <dt>Uptime</dt>
            <dd>
              {device.uptime_seconds == null
                ? "—"
                : `${Math.floor(device.uptime_seconds / 86400)}d ${Math.floor(
                    (device.uptime_seconds % 86400) / 3600,
                  )}h`}
            </dd>
          </div>
          {device.check_type !== "ping_only" && (
            <>
              <div>
                <dt>CPU</dt>
                <dd>
                  {device.cpu_usage_percent == null
                    ? "—"
                    : `${device.cpu_usage_percent}%`}
                </dd>
              </div>
              <div>
                <dt>Memory used</dt>
                <dd>
                  {device.memory_used_bytes == null ||
                  device.memory_total_bytes == null
                    ? "—"
                    : `${(device.memory_used_bytes / 1024 / 1024).toFixed(1)} / ${(device.memory_total_bytes / 1024 / 1024).toFixed(1)} MiB`}
                </dd>
              </div>
              {device.collector === "mikrotik" && (
                <>
                  <div>
                    <dt>Disk used</dt>
                    <dd>
                      {device.disk_used_bytes == null ||
                      device.disk_total_bytes == null
                        ? "—"
                        : `${(device.disk_used_bytes / 1024 / 1024).toFixed(1)} / ${(device.disk_total_bytes / 1024 / 1024).toFixed(1)} MiB`}
                    </dd>
                  </div>
                  <div>
                    <dt>Temperature</dt>
                    <dd>
                      {device.temperature_celsius == null
                        ? "—"
                        : `${device.temperature_celsius} °C`}
                    </dd>
                  </div>
                  <div>
                    <dt>Voltage</dt>
                    <dd>
                      {device.voltage_volts == null
                        ? "—"
                        : `${device.voltage_volts} V`}
                    </dd>
                  </div>
                  <div>
                    <dt>DHCP leases / ARP entries</dt>
                    <dd>
                      {device.dhcp_lease_count ?? "—"} / {device.arp_entry_count ?? "—"}
                    </dd>
                  </div>
                </>
              )}
            </>
          )}
          <div>
            <dt>Serial number</dt>
            <dd className="mono">{device.serial_number ?? "—"}</dd>
          </div>
          <div>
            <dt>Groups</dt>
            <dd>
              {(device.groups ?? []).map((group) => group.name).join(", ") || "—"}
            </dd>
          </div>
          <div>
            <dt>Telemetry collector</dt>
            <dd>{device.collector === "mikrotik" ? "MikroTik" : "Generic SNMP"}</dd>
          </div>
          <div>
            <dt>Check type</dt>
            <dd>
              {formatCheckType(device.check_type)}
              {device.credential_profile
                ? ` · ${device.credential_profile.name}`
                : ""}
            </dd>
          </div>
          {device.check_type === "routeros_api" && (
            <div>
              <dt>API transport</dt>
              <dd>RouterOS REST API with v6 binary API fallback</dd>
            </div>
          )}
          <div>
            <dt>Notes</dt>
            <dd>{device.notes ?? "—"}</dd>
          </div>
        </dl>
      </section>

      {device.check_type !== "ping_only" && (
        <section className="chart-card" aria-labelledby="interfaces-title">
          <div className="chart-heading">
            <div>
              <h2 id="interfaces-title">Interfaces and bandwidth</h2>
              <p className="muted">
                64-bit interface counters · Prometheus rates · speed-based utilization
              </p>
            </div>
            <div className="range-picker" role="group" aria-label="Bandwidth range">
              {BANDWIDTH_RANGES.map((range) => (
                <button
                  key={range.hours}
                  className={`range-button ${
                    range.hours === bandwidthHours ? "range-active" : ""
                  }`}
                  onClick={() => setBandwidthHours(range.hours)}
                >
                  {range.label}
                </button>
              ))}
            </div>
          </div>
          {bandwidthError && (
            <p className="banner banner-error">{bandwidthError}</p>
          )}
          {interfaces.length === 0 ? (
            <p className="muted">
              No interfaces discovered yet. Check connectivity and the
              poller logs.
            </p>
          ) : (
            <>
              <div className="table-wrap">
                <table className="device-table">
                  <thead>
                    <tr>
                      <th>Interface</th>
                      <th>Status</th>
                      <th>Reported speed</th>
                      <th>Override</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {interfaces.map((item) => (
                      <tr
                        key={item.id}
                        className={
                          item.id === selectedInterfaceId ? "selected-row" : ""
                        }
                        onClick={() => setSelectedInterfaceId(item.id)}
                      >
                        <td>
                          <strong>{item.name}</strong>
                          {item.alias && <span className="muted"> · {item.alias}</span>}
                        </td>
                        <td>{item.oper_status === 1 ? "Up" : item.oper_status == null ? "—" : "Down"}</td>
                        <td>
                          {item.link_speed_mbps == null
                            ? "—"
                            : `${item.link_speed_mbps} Mbps`}
                        </td>
                        <td>
                          {item.link_speed_override_mbps == null
                            ? "—"
                            : `${item.link_speed_override_mbps} Mbps`}
                        </td>
                        <td>
                          <button
                            className="link-button"
                            onClick={(event) => {
                              event.stopPropagation();
                              void updateLinkSpeed(item);
                            }}
                          >
                            Set speed
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {interfaceMetrics && (
                <>
                <div className="stats-grid">
                  <div className="stat-card">
                    <span className="stat-label">Inbound now</span>
                    <strong className="stat-value">
                      {formatMbps(latest(interfaceMetrics.in_bits_per_second))}
                    </strong>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Outbound now</span>
                    <strong className="stat-value">
                      {formatMbps(latest(interfaceMetrics.out_bits_per_second))}
                    </strong>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">
                      Inbound peak ({bandwidthRangeLabel})
                    </span>
                    <strong className="stat-value">
                      {formatMbps(peak(interfaceMetrics.in_bits_per_second))}
                    </strong>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">
                      Outbound peak ({bandwidthRangeLabel})
                    </span>
                    <strong className="stat-value">
                      {formatMbps(peak(interfaceMetrics.out_bits_per_second))}
                    </strong>
                  </div>
                </div>
                <div className="interface-charts">
                  <div className="chart-card">
                    <h3>{interfaceMetrics.interface_name} traffic</h3>
                    <p className="muted">Inbound · Mbps</p>
                    <LatencyChart
                      points={interfaceMetrics.in_bits_per_second.map((point) => ({
                        ...point,
                        value: point.value / 1_000_000,
                      }))}
                      unit="Mbps"
                    />
                    <p className="muted">Outbound · Mbps</p>
                    <LatencyChart
                      points={interfaceMetrics.out_bits_per_second.map((point) => ({
                        ...point,
                        value: point.value / 1_000_000,
                      }))}
                      unit="Mbps"
                      lineColor="#63a9e3"
                    />
                  </div>
                  <div className="chart-card">
                    <h3>Error rate (errors/sec)</h3>
                    <p className="muted">Inbound errors</p>
                    <LatencyChart
                      points={interfaceMetrics.in_errors_per_second}
                      unit="/s"
                    />
                    <p className="muted">Outbound errors</p>
                    <LatencyChart
                      points={interfaceMetrics.out_errors_per_second}
                      unit="/s"
                      lineColor="#63a9e3"
                    />
                  </div>
                  <div className="chart-card">
                    <h3>Discard rate (discards/sec)</h3>
                    <p className="muted">Inbound discards</p>
                    <LatencyChart
                      points={interfaceMetrics.in_discards_per_second}
                      unit="/s"
                    />
                    <p className="muted">Outbound discards</p>
                    <LatencyChart
                      points={interfaceMetrics.out_discards_per_second}
                      unit="/s"
                      lineColor="#63a9e3"
                    />
                  </div>
                  <div className="chart-card">
                    <h3>Bandwidth utilization</h3>
                    <p className="muted">Inbound</p>
                    <LatencyChart
                      points={interfaceMetrics.in_utilization.map((point) => ({
                        ...point,
                        value: point.value * 100,
                      }))}
                      unit="%"
                    />
                    <p className="muted">Outbound</p>
                    <LatencyChart
                      points={interfaceMetrics.out_utilization.map((point) => ({
                        ...point,
                        value: point.value * 100,
                      }))}
                      unit="%"
                      lineColor="#63a9e3"
                    />
                  </div>
                </div>
                </>
              )}
            </>
          )}
        </section>
      )}
    </section>
  );
}

export default DeviceDetailPage;
