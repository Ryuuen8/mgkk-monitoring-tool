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

function average(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function DeviceDetailPage({ deviceId, onBack, onEdit }: DeviceDetailPageProps) {
  const [device, setDevice] = useState<DeviceDetail | null>(null);
  const [metrics, setMetrics] = useState<DeviceMetrics | null>(null);
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [rangeMinutes, setRangeMinutes] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const range = RANGES.find((item) => item.minutes === rangeMinutes) ?? RANGES[1];

    const load = async () => {
      const [deviceResponse, metricsResponse, statusResponse] = await Promise.all([
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
      setLoading(false);
    };

    void load();
    const timer = window.setInterval(() => void load(), 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [deviceId, rangeMinutes]);

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
              <dd>HTTPS REST API</dd>
            </div>
          )}
          <div>
            <dt>Notes</dt>
            <dd>{device.notes ?? "—"}</dd>
          </div>
        </dl>
      </section>
    </section>
  );
}

export default DeviceDetailPage;
