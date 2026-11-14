import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  errorMessage,
  formatCollector,
  formatLatency,
  type DeviceMetricSeries,
  type InterfaceMetrics,
  type NetworkInterface,
} from "../api/client";

type Props = {
  deviceId: string;
  onBack: () => void;
  onEdit: (id: string) => void;
};

echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const RANGE_OPTIONS = [
  { hours: 24, label: "24 hours", step: 300 },
  { hours: 168, label: "7 days", step: 1800 },
  { hours: 720, label: "30 days", step: 3600 },
] as const;

function latest(series: InterfaceMetrics["in_bits_per_second"]): number | undefined {
  return series.at(-1)?.value;
}

function statusLabel(value: number | null): string {
  if (value === 1) return "Up";
  if (value === 2) return "Down";
  return value == null ? "Unknown" : `Status ${value}`;
}

function formatRate(value: number | undefined): string {
  return value == null ? "—" : `${(value / 1_000_000).toFixed(2)} Mbps`;
}

function formatSpeed(value: number | null): string {
  return value == null ? "—" : `${value.toLocaleString()} Mbps`;
}

function formatMemory(used: number | null, total: number | null): string {
  if (used == null || total == null || total <= 0) return "—";
  return `${((used / total) * 100).toFixed(0)}%`;
}

function DeviceDetailV1({ deviceId, onBack, onEdit }: Props) {
  const [rangeHours, setRangeHours] = useState<(typeof RANGE_OPTIONS)[number]["hours"]>(24);
  const [reachabilityRangeMinutes, setReachabilityRangeMinutes] = useState(1440);
  const [selectedInterfaceId, setSelectedInterfaceId] = useState<number | null>(null);
  const [editingInterfaceId, setEditingInterfaceId] = useState<number | null>(null);
  const [speedOverride, setSpeedOverride] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingSpeed, setSavingSpeed] = useState(false);
  const trafficChartElement = useRef<HTMLDivElement>(null);
  const errorChartElement = useRef<HTMLDivElement>(null);
  const reachabilityChartElement = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const deviceQuery = useQuery({
    queryKey: ["v1-device", deviceId],
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices/{device_id}", {
        params: { path: { device_id: deviceId } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data;
    },
  });
  const metricsQuery = useQuery({
    queryKey: ["v1-device-metrics", deviceId, reachabilityRangeMinutes],
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices/{device_id}/metrics", {
        params: {
          path: { device_id: deviceId },
          query: { range_minutes: reachabilityRangeMinutes, step_seconds: 30 },
        },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data;
    },
    refetchInterval: 30_000,
  });
  const interfacesQuery = useQuery({
    queryKey: ["v1-device-interfaces", deviceId],
    queryFn: async () => {
      const response = await api.GET("/api/v1/devices/{device_id}/interfaces", {
        params: { path: { device_id: deviceId } },
      });
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data;
    },
    refetchInterval: 30_000,
  });

  const interfaces = interfacesQuery.data ?? [];
  const effectiveInterfaceId =
    interfaces.some((item) => item.id === selectedInterfaceId)
      ? selectedInterfaceId
      : (interfaces[0]?.id ?? null);
  const range = RANGE_OPTIONS.find((option) => option.hours === rangeHours)!;
  const interfaceMetricsQuery = useQuery({
    queryKey: ["v1-device-interface-metrics", deviceId, rangeHours],
    enabled: interfaces.length > 0,
    queryFn: async () => {
      const response = await api.GET(
        "/api/v1/devices/{device_id}/interfaces/metrics",
        {
          params: {
            path: { device_id: deviceId },
            query: { range_hours: range.hours, step_seconds: range.step },
          },
        },
      );
      if (response.error) throw new Error(errorMessage(response.error));
      return response.data;
    },
    refetchInterval: 60_000,
  });
  const interfaceMetrics = new Map(
    (interfaceMetricsQuery.data ?? []).map((item) => [item.interface_id, item]),
  );
  const selectedInterface = interfaces.find(
    (item) => item.id === effectiveInterfaceId,
  );
  const selectedMetrics =
    effectiveInterfaceId == null
      ? undefined
      : interfaceMetrics.get(effectiveInterfaceId);

  useEffect(() => {
    const element = reachabilityChartElement.current;
    const metrics: DeviceMetricSeries | undefined = metricsQuery.data;
    if (!element || !metrics) return;
    const chart = echarts.init(element);
    chart.setOption({
      backgroundColor: "transparent",
      color: ["#68d2ad", "#e7aa64"],
      animation: false,
      grid: { left: 64, right: 64, top: 42, bottom: 36 },
      legend: { top: 4, textStyle: { color: "#9aa7b2" } },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      xAxis: {
        type: "time",
        axisLabel: { color: "#84919c" },
        axisLine: { lineStyle: { color: "#35414c" } },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: "value",
          name: "Latency (ms)",
          nameTextStyle: { color: "#9aa7b2" },
          axisLabel: { color: "#84919c" },
          splitLine: { lineStyle: { color: "#28323c" } },
        },
        {
          type: "value",
          name: "Packet loss (%)",
          min: 0,
          max: 100,
          nameTextStyle: { color: "#9aa7b2" },
          axisLabel: { color: "#84919c" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Latency",
          type: "line",
          showSymbol: false,
          smooth: true,
          yAxisIndex: 0,
          data: metrics.latency.map((point) => [point.t * 1000, point.value]),
        },
        {
          name: "Packet loss",
          type: "line",
          showSymbol: false,
          step: "middle",
          yAxisIndex: 1,
          data: metrics.packet_loss_percent.map((point) => [
            point.t * 1000,
            point.value,
          ]),
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [metricsQuery.data]);

  useEffect(() => {
    const element = trafficChartElement.current;
    if (!element || !selectedMetrics) return;
    const chart = echarts.init(element);
    chart.setOption({
      backgroundColor: "transparent",
      color: ["#68d2ad", "#e7aa64", "#70a9e8", "#ce7f91"],
      animation: false,
      grid: { left: 62, right: 62, top: 40, bottom: 34 },
      legend: { top: 2, textStyle: { color: "#9aa7b2" } },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      xAxis: {
        type: "time",
        axisLabel: { color: "#84919c" },
        axisLine: { lineStyle: { color: "#35414c" } },
      },
      yAxis: [
        {
          type: "value",
          name: "Mbps",
          nameTextStyle: { color: "#9aa7b2" },
          axisLabel: { color: "#84919c" },
          splitLine: { lineStyle: { color: "#28323c" } },
        },
        {
          type: "value",
          name: "Utilization %",
          min: 0,
          nameTextStyle: { color: "#9aa7b2" },
          axisLabel: { color: "#84919c" },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "Inbound",
          type: "line",
          showSymbol: false,
          data: selectedMetrics.in_bits_per_second.map((point) => [
            point.t * 1000,
            point.value / 1_000_000,
          ]),
        },
        {
          name: "Outbound",
          type: "line",
          showSymbol: false,
          data: selectedMetrics.out_bits_per_second.map((point) => [
            point.t * 1000,
            point.value / 1_000_000,
          ]),
        },
        {
          name: "Inbound utilization",
          type: "line",
          showSymbol: false,
          yAxisIndex: 1,
          data: selectedMetrics.in_utilization_percent.map((point) => [
            point.t * 1000,
            point.value,
          ]),
        },
        {
          name: "Outbound utilization",
          type: "line",
          showSymbol: false,
          yAxisIndex: 1,
          data: selectedMetrics.out_utilization_percent.map((point) => [
            point.t * 1000,
            point.value,
          ]),
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [selectedMetrics]);

  useEffect(() => {
    const element = errorChartElement.current;
    if (!element || !selectedMetrics) return;
    const chart = echarts.init(element);
    chart.setOption({
      backgroundColor: "transparent",
      color: ["#e7aa64", "#ce7f91", "#70a9e8", "#b58be0", "#68d2ad"],
      animation: false,
      grid: { left: 62, right: 20, top: 40, bottom: 34 },
      legend: { top: 2, textStyle: { color: "#9aa7b2" } },
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "time",
        axisLabel: { color: "#84919c" },
        axisLine: { lineStyle: { color: "#35414c" } },
      },
      yAxis: {
        type: "value",
        name: "Events / second",
        min: 0,
        nameTextStyle: { color: "#9aa7b2" },
        axisLabel: { color: "#84919c" },
        splitLine: { lineStyle: { color: "#28323c" } },
      },
      series: [
        ["Inbound errors", selectedMetrics.in_errors_per_second],
        ["Outbound errors", selectedMetrics.out_errors_per_second],
        ["CRC/FCS errors", selectedMetrics.crc_errors_per_second],
        ["Inbound discards", selectedMetrics.in_discards_per_second],
        ["Outbound discards", selectedMetrics.out_discards_per_second],
      ].map(([name, series]) => ({
        name,
        type: "line",
        showSymbol: false,
        data: (series as InterfaceMetrics["in_errors_per_second"]).map(
          (point) => [point.t * 1000, point.value],
        ),
      })),
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [selectedMetrics]);

  const saveOverride = async (item: NetworkInterface) => {
    setSavingSpeed(true);
    setSaveError(null);
    try {
      const response = await api.PATCH(
        "/api/v1/devices/{device_id}/interfaces/{interface_id}",
        {
          params: {
            path: { device_id: deviceId, interface_id: item.id },
          },
          body: {
            link_speed_override_mbps: speedOverride
              ? Number(speedOverride)
              : null,
          },
        },
      );
      if (response.error) throw new Error(errorMessage(response.error));
      await queryClient.invalidateQueries({
        queryKey: ["v1-device-interfaces", deviceId],
      });
      setEditingInterfaceId(null);
    } catch (reason: unknown) {
      setSaveError(errorMessage(reason));
    } finally {
      setSavingSpeed(false);
    }
  };

  const device = deviceQuery.data;
  const latestLatency = metricsQuery.data?.latency.at(-1)?.value;
  const latestLoss = metricsQuery.data?.packet_loss_percent.at(-1)?.value;
  const liveIn = selectedMetrics && latest(selectedMetrics.in_bits_per_second);
  const liveOut = selectedMetrics && latest(selectedMetrics.out_bits_per_second);
  const upCount = interfaces.filter((item) => item.oper_status === 1).length;
  const memoryUsage = device
    ? formatMemory(device.memory_used_bytes, device.memory_total_bytes)
    : "—";
  const healthTiles =
    device?.device_type === "switch"
      ? [
          ["Interfaces up", `${upCount} / ${interfaces.length}`],
          ["CPU", device.cpu_usage_percent == null ? "—" : `${device.cpu_usage_percent}%`],
          ["Temperature", device.temperature_celsius == null ? "—" : `${device.temperature_celsius} °C`],
          ["CRC/FCS errors", interfaces.reduce((total, item) => total + (item.last_crc_errors ?? 0), 0).toLocaleString()],
        ]
      : [
          ["CPU", device?.cpu_usage_percent == null ? "—" : `${device.cpu_usage_percent}%`],
          ["Memory", memoryUsage],
          ["Temperature", device?.temperature_celsius == null ? "—" : `${device.temperature_celsius} °C`],
          ["Uptime", device?.uptime_seconds == null ? "—" : `${Math.floor(device.uptime_seconds / 86400)} days`],
        ];
  healthTiles.push(
    [
      "Fan health",
      device?.fans_ok == null ? "—" : device.fans_ok ? "Normal" : "Alert",
    ],
    [
      "Power supplies",
      device?.power_supplies_ok == null
        ? "—"
        : device.power_supplies_ok
          ? "Normal"
          : "Alert",
    ],
  );
  if (device?.fan_speed_rpm != null) {
    healthTiles.push(["Fan speed", `${device.fan_speed_rpm} RPM`]);
  }

  if (deviceQuery.isPending) {
    return <section className="page-section muted">Loading device…</section>;
  }
  if (deviceQuery.error || !device) {
    return (
      <section className="page-section">
        <p className="banner banner-error">
          {errorMessage(deviceQuery.error ?? "Device not found")}
        </p>
        <button className="button" onClick={onBack}>
          Back to inventory
        </button>
      </section>
    );
  }

  return (
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            INVENTORY <span> / </span> DEVICE DETAIL
          </p>
          <h1>{device.name}</h1>
          <p className="subtitle">
            Stable ID <span className="mono">{device.id}</span>
          </p>
        </div>
        <div className="detail-actions">
          <button className="button" onClick={onBack}>Back</button>
          <button className="button button-primary" onClick={() => onEdit(device.id)}>
            Edit device
          </button>
        </div>
      </div>

      <div className="detail-grid">
        {healthTiles.map(([label, value]) => (
          <article className="service-card detail-card" key={label}>
            <span className="detail-label">{label}</span>
            <span className="mono">{value}</span>
          </article>
        ))}
        <article className="service-card detail-card">
          <span className="detail-label">Collector</span>
          <span className={`collector-badge collector-${device.collector}`}>
            {formatCollector(device.collector)}
          </span>
        </article>
        <article className="service-card detail-card">
          <span className="detail-label">Latency / loss</span>
          <span className="mono">
            {formatLatency(latestLatency)} · {latestLoss == null ? "—" : `${latestLoss.toFixed(1)}%`}
          </span>
        </article>
        {device.device_type !== "switch" && (
          <article className="service-card detail-card">
            <span className="detail-label">Voltage</span>
            <span className="mono">
              {device.voltage_volts == null ? "—" : `${device.voltage_volts} V`}
            </span>
          </article>
        )}
      </div>

      {interfacesQuery.error && (
        <p className="banner banner-error">
          Interfaces unavailable: {errorMessage(interfacesQuery.error)}
        </p>
      )}
      <div className="section-heading chart-heading">
        <h2>Interfaces</h2>
        <label className="range-picker">
          History
          <select
            value={rangeHours}
            onChange={(event) =>
              setRangeHours(Number(event.target.value) as typeof rangeHours)
            }
          >
            {RANGE_OPTIONS.map((option) => (
              <option value={option.hours} key={option.hours}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>
      {saveError && <p className="banner banner-error">{saveError}</p>}
      {interfacesQuery.isPending ? (
        <p className="muted">Loading interfaces…</p>
      ) : interfaces.length === 0 ? (
        <p className="muted">No interfaces have been collected yet.</p>
      ) : (
        <div className="table-wrap">
        <table className="device-table interface-table">
            <thead>
              <tr>
                <th>Interface</th>
                <th>Admin / oper</th>
                <th>Effective speed</th>
                <th>In / out</th>
                <th>Utilization</th>
                <th>Errors / CRC / discards</th>
              </tr>
            </thead>
            <tbody>
              {interfaces.map((item) => {
                const metrics = interfaceMetrics.get(item.id);
                const inRate = metrics && latest(metrics.in_bits_per_second);
                const outRate = metrics && latest(metrics.out_bits_per_second);
                const inUtil = metrics && latest(metrics.in_utilization_percent);
                const outUtil = metrics && latest(metrics.out_utilization_percent);
                const speed = item.link_speed_override_mbps ?? item.link_speed_mbps;
                return (
                  <tr
                    key={item.id}
                    className={item.id === effectiveInterfaceId ? "selected-row" : ""}
                    onClick={() => setSelectedInterfaceId(item.id)}
                  >
                    <td>
                      <button
                        className="interface-select"
                        onClick={() => setSelectedInterfaceId(item.id)}
                      >
                        {item.name}
                      </button>
                      {item.alias && <small className="muted">{item.alias}</small>}
                    </td>
                    <td>{statusLabel(item.admin_status)} / {statusLabel(item.oper_status)}</td>
                    <td>
                      {editingInterfaceId === item.id ? (
                        <div className="speed-editor">
                          <input
                            aria-label={`Speed override for ${item.name} in Mbps`}
                            type="number"
                            min="1"
                            value={speedOverride}
                            placeholder={String(item.link_speed_mbps ?? "")}
                            onChange={(event) => setSpeedOverride(event.target.value)}
                          />
                          <button
                            className="button button-small"
                            disabled={savingSpeed}
                            onClick={() => void saveOverride(item)}
                          >
                            Save
                          </button>
                          <button
                            className="button button-small"
                            disabled={savingSpeed}
                            onClick={() => setEditingInterfaceId(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          className="interface-select"
                          title="Edit manual speed override"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSpeedOverride(
                              item.link_speed_override_mbps == null
                                ? ""
                                : String(item.link_speed_override_mbps),
                            );
                            setEditingInterfaceId(item.id);
                          }}
                        >
                          {formatSpeed(speed)} <small>edit</small>
                        </button>
                      )}
                    </td>
                    <td>{formatRate(inRate)} / {formatRate(outRate)}</td>
                    <td>{inUtil == null ? "—" : `${inUtil.toFixed(1)}%`} / {outUtil == null ? "—" : `${outUtil.toFixed(1)}%`}</td>
                    <td>
                      {item.last_in_errors ?? 0} / {item.last_out_errors ?? 0} ·{" "}
                      {item.last_crc_errors ?? 0} · {item.last_in_discards ?? 0} / {item.last_out_discards ?? 0}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selectedInterface && (
        <>
          <div className="section-heading chart-heading">
            <h2>Bandwidth · {selectedInterface.name}</h2>
            <span className="muted">
              Current: {formatRate(liveIn)} in / {formatRate(liveOut)} out
            </span>
          </div>
          {interfaceMetricsQuery.error && (
            <p className="banner banner-error">
              Interface metrics unavailable: {errorMessage(interfaceMetricsQuery.error)}
            </p>
          )}
          {selectedMetrics ? (
            <>
              <div
                className="echarts-container"
                ref={trafficChartElement}
                role="img"
                aria-label={`${selectedInterface.name} bandwidth and utilization`}
              />
              <h3 className="section-subheading">Errors and discards</h3>
              <div
                className="echarts-container"
                ref={errorChartElement}
                role="img"
                aria-label={`${selectedInterface.name} errors and discards`}
              />
            </>
          ) : (
            <p className="muted">Loading interface metrics…</p>
          )}
        </>
      )}

      {metricsQuery.error && (
        <p className="banner banner-error">
          Reachability metrics unavailable: {errorMessage(metricsQuery.error)}
        </p>
      )}
      <div className="section-heading chart-heading">
        <h2>Reachability history</h2>
        <label className="range-picker">
          Range
          <select
            value={reachabilityRangeMinutes}
            onChange={(event) =>
              setReachabilityRangeMinutes(Number(event.target.value))
            }
          >
            <option value={60}>1 hour</option>
            <option value={360}>6 hours</option>
            <option value={1440}>24 hours</option>
          </select>
        </label>
      </div>
      {metricsQuery.isPending ? (
        <p className="muted">Loading reachability history…</p>
      ) : (
        <div
          className="echarts-container"
          ref={reachabilityChartElement}
          role="img"
          aria-label="Latency and packet loss time series"
        />
      )}
      <p className="muted v1-device-meta">
        Role: {device.device_type} · MAC: {device.mac_address ?? "Not recorded"} · Parent:{" "}
        {device.parent_device_id ?? "None"} · {device.active ? "Polling enabled" : "Polling paused"}
      </p>
    </section>
  );
}

export default DeviceDetailV1;
