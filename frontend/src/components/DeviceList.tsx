import { useEffect, useState } from "react";
import {
  api,
  errorMessage,
  formatCheckType,
  formatDeviceType,
  formatLatency,
  formatLoss,
  formatTimestamp,
  type DeviceRead,
  type DeviceStatus,
  type Site,
} from "../api/client";

type DeviceListProps = {
  refreshToken: number;
  onAdd: () => void;
  onOpen: (id: number) => void;
  onEdit: (id: number) => void;
  onDeleted: () => void;
};

function statusLabel(status: DeviceStatus | undefined): string {
  if (!status || status.up == null) return "No data";
  return status.up ? "Online" : "Offline";
}

function statusClass(status: DeviceStatus | undefined): string {
  if (!status || status.up == null) return "status-unknown";
  return status.up ? "status-online" : "status-offline";
}

function DeviceList({
  refreshToken,
  onAdd,
  onOpen,
  onEdit,
  onDeleted,
}: DeviceListProps) {
  const [devices, setDevices] = useState<DeviceRead[]>([]);
  const [statuses, setStatuses] = useState<Record<number, DeviceStatus>>({});
  const [sites, setSites] = useState<Record<number, Site>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const [deviceResponse, siteResponse] = await Promise.all([
        api.GET("/api/devices", { params: { query: { limit: 200 } } }),
        api.GET("/api/sites", { params: { query: { limit: 200 } } }),
      ]);
      if (cancelled) return;

      if (deviceResponse.error) {
        setError(errorMessage(deviceResponse.error));
        setLoading(false);
        return;
      }
      setDevices(deviceResponse.data.items);
      if (siteResponse.data) {
        setSites(
          Object.fromEntries(siteResponse.data.items.map((site) => [site.id, site])),
        );
      }
      setError(null);
      setLoading(false);
    };

    const loadStatuses = async () => {
      const { data, error: statusError } = await api.GET("/api/devices/status");
      if (cancelled || !data) {
        if (!cancelled && statusError) {
          setError(errorMessage(statusError));
        }
        return;
      }
      setStatuses(
        Object.fromEntries(data.items.map((item) => [item.device_id, item])),
      );
    };

    void load();
    void loadStatuses();
    const timer = window.setInterval(() => void loadStatuses(), 10_000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshToken]);

  const handleDelete = async (device: DeviceRead) => {
    if (!window.confirm(`Delete ${device.name}? This cannot be undone.`)) return;
    const { error: deleteError } = await api.DELETE(
      "/api/devices/{device_id}",
      { params: { path: { device_id: device.id } } },
    );
    if (deleteError) {
      setError(errorMessage(deleteError));
      return;
    }
    onDeleted();
  };

  return (
    <section className="page-section" aria-labelledby="devices-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">INVENTORY <span> / </span> DEVICES</p>
          <h1 id="devices-title">Devices</h1>
          <p className="subtitle">
            Live status and latency for ICMP, SNMP and RouterOS API checks.
          </p>
        </div>
        <button className="button button-primary" onClick={onAdd}>
          + Add device
        </button>
      </div>

      {error && <p className="banner banner-error">{error}</p>}

      {loading ? (
        <p className="muted">Loading devices…</p>
      ) : devices.length === 0 ? (
        <div className="empty-state">
          <h2>No devices yet</h2>
          <p>Add your first device and the poller will start checking it.</p>
          <button className="button button-primary" onClick={onAdd}>
            Add device
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="device-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Site</th>
                <th>Type</th>
                <th>Check</th>
                <th>Management IP</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Loss</th>
                <th>Last seen</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => {
                const status = statuses[device.id];
                return (
                  <tr key={device.id}>
                    <td>
                      <button
                        className="link-button device-name"
                        onClick={() => onOpen(device.id)}
                      >
                        {device.name}
                      </button>
                      {device.hostname && (
                        <span className="device-host">{device.hostname}</span>
                      )}
                    </td>
                    <td>{sites[device.site_id]?.name ?? device.site_id}</td>
                    <td>
                      {formatDeviceType(device.device_type)}
                      {device.vendor && (
                        <span className="device-host">{device.vendor}</span>
                      )}
                    </td>
                    <td>{formatCheckType(device.check_type)}</td>
                    <td className="mono">{device.mgmt_ip}</td>
                    <td>
                      <span className={`status ${statusClass(status)}`}>
                        <span className="status-dot" />
                        {statusLabel(status)}
                      </span>
                      {!device.is_active && (
                        <span className="tag">paused</span>
                      )}
                    </td>
                    <td className="mono">{formatLatency(status?.latency_ms)}</td>
                    <td className="mono">
                      {!device.check_type || device.check_type === "ping_only"
                        ? formatLoss(status?.packet_loss)
                        : "—"}
                    </td>
                    <td className="mono muted">
                      {formatTimestamp(status?.last_seen_at ?? device.last_seen_at)}
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          className="link-button"
                          onClick={() => onOpen(device.id)}
                        >
                          Open
                        </button>
                        <button
                          className="link-button"
                          onClick={() => onEdit(device.id)}
                        >
                          Edit
                        </button>
                        <button
                          className="link-button link-danger"
                          onClick={() => void handleDelete(device)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default DeviceList;
