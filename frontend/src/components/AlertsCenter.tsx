import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  errorMessage,
  formatTimestamp,
  type AlertEvent,
  type MaintenanceWindow,
} from "../api/client";
import { useLiveEvents } from "../hooks/useLiveEvents";

type Tab = "active" | "history" | "maintenance" | "syslog";
type ScopeType = "device" | "group" | "site";

type Props = {
  onOpenDevice: (id: string) => void;
};

const SEVERITY_OPTIONS = ["critical", "warning", "info"];

const SYSLOG_SEVERITY_NAMES = [
  "emerg",
  "alert",
  "crit",
  "err",
  "warning",
  "notice",
  "info",
  "debug",
];

function severityClass(severity: string): string {
  return SEVERITY_OPTIONS.includes(severity)
    ? `severity-${severity}`
    : "severity-info";
}

function alertDeviceId(alert: AlertEvent): string | null {
  const value = alert.labels.device_id;
  return typeof value === "string" ? value : null;
}

function formatDuration(start: string, end: string | null): string {
  const startMs = new Date(start).getTime();
  if (Number.isNaN(startMs)) return "—";
  const endMs = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((endMs - startMs) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

function formatEventType(value: string): string {
  return value.replaceAll("_", " ");
}

function toLocalInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function defaultStart(): string {
  const date = new Date();
  date.setSeconds(0, 0);
  return toLocalInput(date);
}

function defaultEnd(): string {
  const date = new Date();
  date.setHours(date.getHours() + 2);
  return toLocalInput(date);
}

function AlertsCenter({ onOpenDevice }: Props) {
  const [tab, setTab] = useState<Tab>("active");
  const [severityFilter, setSeverityFilter] = useState("");
  const [message, setMessage] = useState<{
    tone: "error" | "success";
    text: string;
  } | null>(null);

  const [windowName, setWindowName] = useState("");
  const [scope, setScope] = useState<ScopeType>("device");
  const [targetId, setTargetId] = useState("");
  const [startsAt, setStartsAt] = useState(defaultStart);
  const [endsAt, setEndsAt] = useState(defaultEnd);
  const [suppress, setSuppress] = useState(true);

  const queryClient = useQueryClient();

  useLiveEvents((event) => {
    if (event.type === "alert_fired" || event.type === "alert_resolved") {
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } else if (event.type === "syslog_event") {
      void queryClient.invalidateQueries({ queryKey: ["syslog"] });
    }
  });

  const showAlerts = tab === "active" || tab === "history";
  const alertStatus = tab === "history" ? "resolved" : "firing";

  const alertsQuery = useQuery({
    queryKey: ["alerts", alertStatus, severityFilter],
    enabled: showAlerts,
    queryFn: async () => {
      const response = await api.GET("/api/v1/alerts", {
        params: {
          query: {
            status: alertStatus,
            severity: severityFilter || undefined,
            limit: 100,
          },
        },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
    refetchInterval: tab === "active" ? 15_000 : false,
  });

  const windowsQuery = useQuery({
    queryKey: ["maintenance-windows"],
    enabled: tab === "maintenance",
    queryFn: async () => {
      const response = await api.GET("/api/v1/maintenance-windows", {
        params: { query: { active_only: false, limit: 100 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });

  const devicesQuery = useQuery({
    queryKey: ["maintenance-targets", "devices"],
    enabled: tab === "maintenance",
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices", {
        params: { query: { limit: 200 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });

  const sitesQuery = useQuery({
    queryKey: ["maintenance-targets", "sites"],
    enabled: tab === "maintenance",
    queryFn: async () => {
      const response = await api.GET("/api/v1/sites", {
        params: { query: { limit: 200 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });

  const groupsQuery = useQuery({
    queryKey: ["maintenance-targets", "groups"],
    enabled: tab === "maintenance",
    queryFn: async () => {
      const response = await api.GET("/api/v1/groups", {
        params: { query: { limit: 200 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
  });

  const syslogQuery = useQuery({
    queryKey: ["syslog"],
    enabled: tab === "syslog",
    queryFn: async () => {
      const response = await api.GET("/api/v1/syslog", {
        params: { query: { limit: 100 } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data.items;
    },
    refetchInterval: 15_000,
  });

  const targets = useMemo(() => {
    if (scope === "site") {
      return (sitesQuery.data ?? []).map((site) => ({
        id: site.id,
        name: site.name,
      }));
    }
    if (scope === "group") {
      return (groupsQuery.data ?? []).map((group) => ({
        id: group.id,
        name: group.name,
      }));
    }
    return (devicesQuery.data ?? []).map((device) => ({
      id: device.id,
      name: device.name,
    }));
  }, [scope, devicesQuery.data, sitesQuery.data, groupsQuery.data]);

  const targetNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const device of devicesQuery.data ?? []) {
      names.set(device.id, device.name);
    }
    for (const site of sitesQuery.data ?? []) names.set(site.id, site.name);
    for (const group of groupsQuery.data ?? []) names.set(group.id, group.name);
    return names;
  }, [devicesQuery.data, sitesQuery.data, groupsQuery.data]);

  const acknowledge = async (alert: AlertEvent) => {
    setMessage(null);
    try {
      const response = await api.POST("/api/v1/alerts/{alert_id}/ack", {
        params: { path: { alert_id: alert.id } },
        body: { acknowledged_by: "operator" },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      void queryClient.invalidateQueries({ queryKey: ["alerts"] });
    } catch (reason: unknown) {
      setMessage({ tone: "error", text: errorMessage(reason) });
    }
  };

  const createWindow = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    if (!windowName.trim()) {
      setMessage({ tone: "error", text: "Give the window a name." });
      return;
    }
    if (!targetId) {
      setMessage({ tone: "error", text: `Select a ${scope} for the window.` });
      return;
    }
    const start = new Date(startsAt);
    const end = new Date(endsAt);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      setMessage({ tone: "error", text: "Enter a valid start and end time." });
      return;
    }
    if (end <= start) {
      setMessage({ tone: "error", text: "The end must be after the start." });
      return;
    }
    try {
      const response = await api.POST("/api/v1/maintenance-windows", {
        body: {
          name: windowName.trim(),
          scope_type: scope,
          target_id: targetId,
          starts_at: start.toISOString(),
          ends_at: end.toISOString(),
          suppress_notifications: suppress,
          created_by: "operator",
        },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      setWindowName("");
      setStartsAt(defaultStart());
      setEndsAt(defaultEnd());
      setMessage({ tone: "success", text: "Maintenance window created." });
      void queryClient.invalidateQueries({ queryKey: ["maintenance-windows"] });
    } catch (reason: unknown) {
      setMessage({ tone: "error", text: errorMessage(reason) });
    }
  };

  const deleteWindow = async (item: MaintenanceWindow) => {
    if (
      !window.confirm(
        `Delete maintenance window "${item.name}"? Matching silences are released.`,
      )
    ) {
      return;
    }
    setMessage(null);
    try {
      const response = await api.DELETE(
        "/api/v1/maintenance-windows/{window_id}",
        { params: { path: { window_id: item.id } } },
      );
      if (response.error) throw new Error(errorMessage(response.error));
      void queryClient.invalidateQueries({ queryKey: ["maintenance-windows"] });
    } catch (reason: unknown) {
      setMessage({ tone: "error", text: errorMessage(reason) });
    }
  };

  const windowTargetName = (window: MaintenanceWindow): string => {
    const id =
      window.scope_type === "site"
        ? window.site_id
        : window.scope_type === "group"
          ? window.group_id
          : window.device_id;
    if (!id) return "—";
    return targetNames.get(id) ?? id;
  };

  const alerts = alertsQuery.data ?? [];
  const windows = windowsQuery.data ?? [];
  const syslog = syslogQuery.data ?? [];

  return (
    <section className="page-section" aria-labelledby="alerts-title">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            OPERATIONS <span> / </span> ALERTS
          </p>
          <h1 id="alerts-title">Alert center</h1>
          <p className="subtitle">
            Live alert state, maintenance windows and recent syslog events.
          </p>
        </div>
      </div>

      {message && (
        <p
          className={`banner ${
            message.tone === "error" ? "banner-error" : "banner-success"
          }`}
        >
          {message.text}
        </p>
      )}

      <div className="segmented" role="tablist" aria-label="Alert views">
        {(
          [
            ["active", "Active"],
            ["history", "History"],
            ["maintenance", "Maintenance"],
            ["syslog", "Syslog"],
          ] as [Tab, string][]
        ).map(([value, label]) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            className={`segmented-button ${tab === value ? "segmented-active" : ""}`}
            onClick={() => {
              setTab(value);
              setMessage(null);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {showAlerts && (
        <>
          <div className="inventory-filters">
            <label>
              Severity
              <select
                value={severityFilter}
                onChange={(event) => setSeverityFilter(event.target.value)}
              >
                <option value="">All severities</option>
                {SEVERITY_OPTIONS.map((severity) => (
                  <option key={severity} value={severity}>
                    {severity.charAt(0).toUpperCase() + severity.slice(1)}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {alertsQuery.error && (
            <p className="banner banner-error">
              {errorMessage(alertsQuery.error)}
            </p>
          )}
          {alertsQuery.isPending ? (
            <p className="muted">Loading alerts…</p>
          ) : alerts.length === 0 ? (
            <div className="empty-state">
              <h2>{tab === "active" ? "No active alerts" : "No resolved alerts"}</h2>
              <p>
                {tab === "active"
                  ? "Prometheus has not fired anything since the last check."
                  : "Resolved alerts will be listed here."}
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="device-table alert-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Alert</th>
                    <th>Device</th>
                    <th>Site</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th>State</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((alert) => {
                    const deviceId = alertDeviceId(alert);
                    return (
                      <tr key={alert.id}>
                        <td>
                          <span
                            className={`severity ${severityClass(alert.severity)}`}
                          >
                            {alert.severity}
                          </span>
                        </td>
                        <td>
                          <span className="mono">{alert.alertname}</span>
                          {alert.summary && (
                            <span className="device-host">{alert.summary}</span>
                          )}
                        </td>
                        <td>
                          {deviceId ? (
                            <button
                              className="link-button"
                              onClick={() => onOpenDevice(deviceId)}
                            >
                              {alert.device_name ?? deviceId}
                            </button>
                          ) : (
                            (alert.device_name ?? "—")
                          )}
                        </td>
                        <td>{alert.site ?? "—"}</td>
                        <td className="mono">
                          {formatTimestamp(alert.starts_at)}
                        </td>
                        <td className="mono">
                          {formatDuration(alert.starts_at, alert.ends_at)}
                        </td>
                        <td>
                          <span
                            className={`status status-${
                              alert.status === "firing" ? "offline" : "online"
                            }`}
                          >
                            <span className="status-dot" />
                            {alert.status}
                          </span>
                          {alert.suppressed && <span className="tag">silenced</span>}
                          {alert.acknowledged_at && (
                            <span className="tag">
                              ack · {alert.acknowledged_by ?? "operator"}
                            </span>
                          )}
                        </td>
                        <td>
                          <div className="row-actions">
                            {alert.status === "firing" &&
                              !alert.acknowledged_at && (
                                <button
                                  className="link-button"
                                  onClick={() => void acknowledge(alert)}
                                >
                                  Acknowledge
                                </button>
                              )}
                            {deviceId && (
                              <button
                                className="link-button"
                                onClick={() => onOpenDevice(deviceId)}
                              >
                                Open
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "maintenance" && (
        <>
          <form className="form-card window-form" onSubmit={createWindow}>
            <h2>New maintenance window</h2>
            <div className="form-grid">
              <label className="field">
                Name
                <input
                  value={windowName}
                  onChange={(event) => setWindowName(event.target.value)}
                  placeholder="Core switch firmware upgrade"
                />
              </label>
              <label className="field">
                Scope
                <select
                  value={scope}
                  onChange={(event) => {
                    setScope(event.target.value as ScopeType);
                    setTargetId("");
                  }}
                >
                  <option value="device">Device</option>
                  <option value="group">Group</option>
                  <option value="site">Site</option>
                </select>
              </label>
              <label className="field">
                Target
                <select
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                >
                  <option value="">Select a {scope}…</option>
                  {targets.map((target) => (
                    <option key={target.id} value={target.id}>
                      {target.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Starts
                <input
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                />
              </label>
              <label className="field">
                Ends
                <input
                  type="datetime-local"
                  value={endsAt}
                  onChange={(event) => setEndsAt(event.target.value)}
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={suppress}
                  onChange={(event) => setSuppress(event.target.checked)}
                />
                Suppress Alertmanager notifications
              </label>
            </div>
            <div className="form-actions">
              <button className="button button-primary" type="submit">
                Create window
              </button>
            </div>
          </form>

          {windowsQuery.error && (
            <p className="banner banner-error">
              {errorMessage(windowsQuery.error)}
            </p>
          )}
          {windowsQuery.isPending ? (
            <p className="muted">Loading maintenance windows…</p>
          ) : windows.length === 0 ? (
            <div className="empty-state">
              <h2>No maintenance windows</h2>
              <p>Create a window to silence alerts during planned work.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="device-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Scope</th>
                    <th>Target</th>
                    <th>Starts</th>
                    <th>Ends</th>
                    <th>Silenced</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {windows.map((window) => (
                    <tr key={window.id}>
                      <td>{window.name}</td>
                      <td>{window.scope_type}</td>
                      <td>{windowTargetName(window)}</td>
                      <td className="mono">
                        {formatTimestamp(window.starts_at)}
                      </td>
                      <td className="mono">
                        {formatTimestamp(window.ends_at)}
                      </td>
                      <td>
                        {window.suppress_notifications ? (
                          <span className="tag">
                            {window.silence_ids.length} silence
                            {window.silence_ids.length === 1 ? "" : "s"}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="link-button link-danger"
                            onClick={() => void deleteWindow(window)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "syslog" && (
        <>
          {syslogQuery.error && (
            <p className="banner banner-error">
              {errorMessage(syslogQuery.error)}
            </p>
          )}
          {syslogQuery.isPending ? (
            <p className="muted">Loading syslog events…</p>
          ) : syslog.length === 0 ? (
            <div className="empty-state">
              <h2>No syslog events</h2>
              <p>
                Point devices at UDP/TCP 5514 to retain link, auth and
                configuration events here.
              </p>
            </div>
          ) : (
            <div className="table-wrap">
              <table className="device-table syslog-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Severity</th>
                    <th>Type</th>
                    <th>Source</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {syslog.map((event) => (
                    <tr key={event.id}>
                      <td className="mono">
                        {formatTimestamp(event.occurred_at)}
                      </td>
                      <td>
                        <span className="mono">
                          {SYSLOG_SEVERITY_NAMES[event.severity] ??
                            event.severity}
                        </span>
                      </td>
                      <td>{formatEventType(event.event_type)}</td>
                      <td className="mono">
                        {event.hostname ?? event.source_ip}
                        <span className="device-host">{event.source_ip}</span>
                      </td>
                      <td className="syslog-message">{event.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

export default AlertsCenter;
