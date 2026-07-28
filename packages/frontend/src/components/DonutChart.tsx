/**
 * 纯 SVG 环形图（零图表库依赖，spec 4 §3.1 二十四次修订）。
 * 中心显示总数；调用方负责图例。
 */
export interface DonutSlice {
  label: string;
  value: number;
  color: string;
}

export function DonutChart({
  data,
  size = 180,
  thickness = 26,
  centerValue,
  centerTitle,
}: {
  data: DonutSlice[];
  size?: number;
  thickness?: number;
  /** 中心数值；缺省为各扇区之和 */
  centerValue?: number;
  centerTitle?: string;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);
  const center = centerValue ?? total;
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;

  let offset = 0;
  const arcs = data
    .filter((d) => d.value > 0)
    .map((d) => {
      const frac = d.value / total;
      const dash = frac * circumference;
      const arc = (
        <circle
          key={d.label}
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={d.color}
          strokeWidth={thickness}
          strokeDasharray={`${dash} ${circumference - dash}`}
          strokeDashoffset={-offset}
          transform={`rotate(-90 ${cx} ${cy})`}
        />
      );
      offset += dash;
      return arc;
    });

  return (
    <svg width={size} height={size} role="img">
      {total === 0 ? (
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="#f0f0f0"
          strokeWidth={thickness}
        />
      ) : (
        arcs
      )}
      <text x={cx} y={cy - 6} textAnchor="middle" style={{ fontSize: 26, fontWeight: 600, fill: "#262626" }}>
        {center}
      </text>
      {centerTitle && (
        <text x={cx} y={cy + 18} textAnchor="middle" style={{ fontSize: 12, fill: "#999" }}>
          {centerTitle}
        </text>
      )}
    </svg>
  );
}
