import type { MetricPoint } from "../api/client";

type LatencyChartProps = {
  points: MetricPoint[];
  height?: number;
  unit?: string;
};

const WIDTH = 820;

/** Lightweight dependency-free SVG line chart for a single metric. */
function LatencyChart({ points, height = 240, unit = "ms" }: LatencyChartProps) {
  if (points.length === 0) {
    return (
      <div className="chart-empty" style={{ height }}>
        No samples yet. The poller writes one every poll interval.
      </div>
    );
  }

  const pad = { top: 18, right: 18, bottom: 30, left: 56 };
  const innerWidth = WIDTH - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;

  const first = points[0].t;
  const last = points[points.length - 1].t;
  const span = Math.max(last - first, 1);

  const values = points.map((point) => point.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const min = Math.max(0, rawMin - (rawMax - rawMin) * 0.1);
  const max = rawMax === min ? min + 1 : rawMax + (rawMax - rawMin) * 0.1;

  const x = (t: number) => pad.left + ((t - first) / span) * innerWidth;
  const y = (value: number) =>
    pad.top + (1 - (value - min) / (max - min)) * innerHeight;

  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${x(point.t).toFixed(1)},${y(point.value).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${x(last).toFixed(1)},${pad.top + innerHeight} L${x(first).toFixed(1)},${pad.top + innerHeight} Z`;

  const yTicks = Array.from({ length: 4 }, (_, index) => {
    const value = min + ((max - min) * index) / 3;
    return { value, y: y(value) };
  }).reverse();

  const xTicks = Array.from({ length: 4 }, (_, index) => {
    const t = first + (span * index) / 3;
    return { t, x: x(t) };
  });

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${WIDTH} ${height}`}
      role="img"
      aria-label={`Latency chart with ${points.length} samples`}
    >
      <defs>
        <linearGradient id="latency-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#68d2ad" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#68d2ad" stopOpacity="0" />
        </linearGradient>
      </defs>

      {yTicks.map((tick) => (
        <g key={`y-${tick.value}`}>
          <line
            x1={pad.left}
            x2={WIDTH - pad.right}
            y1={tick.y}
            y2={tick.y}
            className="chart-grid"
          />
          <text x={pad.left - 10} y={tick.y + 4} textAnchor="end" className="chart-label">
            {tick.value.toFixed(1)} {unit}
          </text>
        </g>
      ))}

      {xTicks.map((tick, index) => (
        <text
          key={`x-${index}`}
          x={tick.x}
          y={height - 8}
          textAnchor={index === 0 ? "start" : index === 3 ? "end" : "middle"}
          className="chart-label"
        >
          {new Date(tick.t * 1000).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </text>
      ))}

      <path d={area} fill="url(#latency-fill)" />
      <path d={line} className="chart-line" />
    </svg>
  );
}

export default LatencyChart;
