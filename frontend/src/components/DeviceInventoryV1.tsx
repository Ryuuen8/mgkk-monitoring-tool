import { useQuery } from "@tanstack/react-query";
import {
  api,
  errorMessage,
  formatCollector,
  formatLatency,
  type DeviceV1,
  type DeviceV1Status,
  type Site,
} from "../api/client";

type Props = {
  refreshToken: number;
  onAdd: () => void;
  onOpen: (id: string) => void;
  onEdit: (id: string) => void;
  onDeleted: () => void;
};

function DeviceInventoryV1({
  refreshToken,
  onAdd,
  onOpen,
  onEdit,
  onDeleted,
}: Props) {
  const devicesQuery = useQuery({
    queryKey: ["v1-devices", refreshToken],
    queryFn: async () => {
      const [devices, sites] = await Promise.all([
        api.GET("/api/v1/devices", { params: { query: { limit: 200 } } }),
        api.GET("/api/v1/sites", { params: { query: { limit: 200 } } }),
      ]);
      if (devices.error) throw new Error(errorMessage(devices.error));
      if (sites.error) throw new Error(errorMessage(sites.error));
      return {
        devices: devices.data.items,
        sites: Object.fromEntries(
          sites.data.items.map((site) => [site.id, site]),
        ) as Record<number, Site>,
      };
    },
  });
  const statusQuery = useQuery({
    queryKey: ["v1-device-status"],
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices/status");
      if (response.error) throw new Error(errorMessage(response.error));
      return Object.fromEntries(
        response.data.map((item) => [item.device_id, item]),
      ) as Record<string, DeviceV1Status>;
    },
    refetchInterval: 10_000,
  });

  const removeDevice = async (device: DeviceV1) => {
    if (!window.confirm(`Delete ${device.name}? This cannot be undone.`)) return;
    try {
      const response = await api.DELETE("/api/v1/devices/{device_id}", {
        params: { path: { device_id: device.id } },
      });
      if (response.error) {
        window.alert(errorMessage(response.error));
        return;
      }
      onDeleted();
    } catch (reason: unknown) {
      window.alert(errorMessage(reason));
    }
  };

  const devices = devicesQuery.data?.devices ?? [];
  const sites = devicesQuery.data?.sites ?? {};

  return (
    <section className="page-section" aria-labelledby="devices-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            INVENTORY <span> / </span> DEVICES
          </p>
          <h1 id="devices-title">Device inventory</h1>
          <p className="subtitle">
            Stable device identities with live ICMP reachability.
          </p>
        </div>
        <button className="button button-primary" onClick={onAdd}>
          + Add device
        </button>
      </div>

      {devicesQuery.error && (
        <p className="banner banner-error">
          {errorMessage(devicesQuery.error)}
        </p>
      )}
      {statusQuery.error && (
        <p className="banner banner-error">
          Live status unavailable: {errorMessage(statusQuery.error)}
        </p>
      )}

      {devicesQuery.isPending ? (
        <p className="muted">Loading devices…</p>
      ) : devices.length === 0 ? (
        <div className="empty-state">
          <h2>No devices yet</h2>
          <p>Add a device to start monitoring its reachability.</p>
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
                <th>Collector</th>
                <th>IP address</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Packet loss</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => {
                const status = statusQuery.data?.[device.id];
                const state =
                  status?.up == null ? "unknown" : status.up ? "online" : "offline";
                return (
                  <tr key={device.id}>
                    <td>
                      <button
                        className="link-button device-name"
                        onClick={() => onOpen(device.id)}
                      >
                        {device.name}
                      </button>
                      {device.vendor && (
                        <span className="device-host">{device.vendor}</span>
                      )}
                    </td>
                    <td>{sites[device.site_id]?.name ?? device.site_id}</td>
                    <td>
                      <span className={`collector-badge collector-${device.collector}`}>
                        {formatCollector(device.collector)}
                      </span>
                    </td>
                    <td className="mono">{device.ip_address}</td>
                    <td>
                      <span className={`status status-${state}`}>
                        <span className="status-dot" />
                        {state === "online"
                          ? "Up"
                          : state === "offline"
                            ? "Down"
                            : "No data"}
                      </span>
                      {!device.active && <span className="tag">paused</span>}
                    </td>
                    <td className="mono">
                      {formatLatency(status?.latency_ms)}
                    </td>
                    <td className="mono">
                      {status?.packet_loss_percent == null
                        ? "—"
                        : `${status.packet_loss_percent.toFixed(1)}%`}
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
                          onClick={() => void removeDevice(device)}
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

export default DeviceInventoryV1;
