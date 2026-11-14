import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  errorMessage,
  formatCollector,
  formatLatency,
  formatOsFamily,
  OS_FAMILIES,
  type CollectorV1,
  type DeviceV1,
  type DeviceV1Status,
  type OsFamily,
  type SiteV1,
} from "../api/client";
import { useLiveEvents } from "../hooks/useLiveEvents";

const PAGE_SIZE = 25;

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
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [collectorFilter, setCollectorFilter] = useState<CollectorV1 | "">("");
  const [osFilter, setOsFilter] = useState<OsFamily | "">("");
  const [page, setPage] = useState(0);
  const queryClient = useQueryClient();

  useLiveEvents((event) => {
    if (event.type !== "device_status" || !event.device_id) return;
    const deviceId = event.device_id;
    queryClient.setQueryData<Record<string, DeviceV1Status>>(
      ["v1-device-status"],
      (previous) => {
        const existing = previous?.[deviceId];
        return {
          ...previous,
          [deviceId]: {
            device_id: deviceId,
            name: event.device ?? existing?.name ?? "",
            up: Boolean(event.up),
            latency_ms: event.latency_ms ?? null,
            packet_loss_percent: event.packet_loss_percent ?? null,
            last_seen_at: event.timestamp ?? existing?.last_seen_at ?? null,
          },
        };
      },
    );
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQuery(search.trim());
      setPage(0);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const devicesQuery = useQuery({
    queryKey: [
      "v1-devices",
      refreshToken,
      page,
      query,
      collectorFilter,
      osFilter,
    ],
    queryFn: async () => {
      const [devices, sites] = await Promise.all([
        api.GET("/api/v1/devices", {
          params: {
            query: {
              limit: PAGE_SIZE,
              offset: page * PAGE_SIZE,
              q: query || undefined,
              collector: collectorFilter || undefined,
              os_family: osFilter || undefined,
            },
          },
        }),
        api.GET("/api/v1/sites", { params: { query: { limit: 200 } } }),
      ]);
      if (devices.error) throw new Error(errorMessage(devices.error));
      if (sites.error) throw new Error(errorMessage(sites.error));
      return {
        devices: devices.data.items,
        total: devices.data.total,
        sites: Object.fromEntries(
          sites.data.items.map((site) => [site.id, site]),
        ) as Record<string, SiteV1>,
      };
    },
    placeholderData: (previous) => previous,
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
      setPage(0);
      onDeleted();
    } catch (reason: unknown) {
      window.alert(errorMessage(reason));
    }
  };

  const devices = devicesQuery.data?.devices ?? [];
  const total = devicesQuery.data?.total ?? 0;
  const sites = devicesQuery.data?.sites ?? {};
  const hasFilters = Boolean(query || collectorFilter || osFilter);
  const firstRow = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastRow = Math.min((page + 1) * PAGE_SIZE, total);

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

      <div className="inventory-filters">
        <label>
          Search
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Name, IP, vendor or model"
          />
        </label>
        <label>
          Collector
          <select
            value={collectorFilter}
            onChange={(event) => {
              setCollectorFilter(event.target.value as CollectorV1 | "");
              setPage(0);
            }}
          >
            <option value="">All collectors</option>
            <option value="generic_snmp">Generic SNMP</option>
            <option value="mikrotik">MikroTik</option>
            <option value="cisco">Cisco</option>
          </select>
        </label>
        <label>
          OS family
          <select
            value={osFilter}
            onChange={(event) => {
              setOsFilter(event.target.value as OsFamily | "");
              setPage(0);
            }}
          >
            <option value="">All OS families</option>
            {OS_FAMILIES.map((family) => (
              <option value={family} key={family}>
                {formatOsFamily(family)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {devicesQuery.isPending ? (
        <p className="muted">Loading devices…</p>
      ) : total === 0 && !hasFilters ? (
        <div className="empty-state">
          <h2>No devices yet</h2>
          <p>Add a device to start monitoring its reachability.</p>
          <button className="button button-primary" onClick={onAdd}>
            Add device
          </button>
        </div>
      ) : total === 0 ? (
        <p className="muted">No devices match the current filters.</p>
      ) : (
        <>
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
                    status?.up == null
                      ? "unknown"
                      : status.up
                        ? "online"
                        : "offline";
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
                          <span className="device-host">
                            {device.vendor}
                            {device.os_family
                              ? ` · ${formatOsFamily(device.os_family)}`
                              : ""}
                          </span>
                        )}
                      </td>
                      <td>{sites[device.site_id]?.name ?? device.site_id}</td>
                      <td>
                        <span
                          className={`collector-badge collector-${device.collector}`}
                        >
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
          <div className="pagination">
            <span className="muted">
              {firstRow}–{lastRow} of {total}
              {devicesQuery.isFetching ? " · updating" : ""}
            </span>
            <div className="pagination-actions">
              <button
                className="button"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
              >
                Previous
              </button>
              <button
                className="button"
                disabled={lastRow >= total}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default DeviceInventoryV1;
