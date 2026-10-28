interface ProjectionSparklineProps {
  current: number | null;
  after7Days: number | null;
  after14Days: number | null;
  label: string;
  compact?: boolean;
}

function formatVal(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  return new Intl.NumberFormat().format(Math.round(v));
}

export function ProjectionSparkline({
  current,
  after7Days,
  after14Days,
  label,
  compact = false,
}: ProjectionSparklineProps) {
  const values = [current, after7Days, after14Days];
  const isValid = (v: number | null): v is number =>
    v !== null && Number.isFinite(v) && v >= 0;

  const validVals = values.filter(isValid);
  const maxVal = Math.max(...validVals, 1);

  // SVG coordinate setup
  const baseline = compact ? 34 : 48;
  const chartHeight = compact ? 24 : 34;
  const xCoords = compact ? [18, 58, 98] : [24, 76, 128];
  const width = compact ? 116 : 152;
  const height = compact ? 48 : 70;

  const points = values.map((val, idx) => ({
    x: xCoords[idx],
    y: isValid(val) ? baseline - (val / maxVal) * chartHeight : null,
  }));

  const accessibleText = `${label} stock projection. Current: ${formatVal(
    current
  )} units, 7 days: ${formatVal(after7Days)} units, 14 days: ${formatVal(
    after14Days
  )} units. Future values assume constant consumption and no incoming receipts.`;

  return (
    <div className={`projection-sparkline ${compact ? "compact" : ""}`}>
      <svg
        role="img"
        aria-label={accessibleText}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMinYMin meet"
        className="projection-svg"
      >
        <line
          className="chart-baseline"
          x1={8}
          y1={baseline}
          x2={width - 8}
          y2={baseline}
        />
        {/* Connecting lines */}
        {points.slice(0, -1).map((pt, i) => {
          const next = points[i + 1];
          if (pt.y !== null && next.y !== null) {
            return (
              <line
                key={`line-${i}`}
                className="projection-trend-line"
                x1={pt.x}
                y1={pt.y}
                x2={next.x}
                y2={next.y}
              />
            );
          }
          return null;
        })}
        {/* Points & Labels */}
        {points.map((pt, i) => {
          const val = values[i];
          const stepLabel = ["Now", "+7d", "+14d"][i];
          const hasVal = isValid(val);
          return (
            <g key={`pt-${i}`}>
              {pt.y !== null && (
                <circle
                  className={`projection-dot ${i === 0 ? "current" : "future"}`}
                  cx={pt.x}
                  cy={pt.y}
                  r={compact ? 2.5 : 3.5}
                />
              )}
              <text
                className="projection-num"
                x={pt.x}
                y={baseline + (compact ? 10 : 13)}
                textAnchor="middle"
              >
                {hasVal ? formatVal(val) : "—"}
              </text>
              <text
                className="projection-step"
                x={pt.x}
                y={baseline + (compact ? 18 : 24)}
                textAnchor="middle"
              >
                {stepLabel}
              </text>
            </g>
          );
        })}
      </svg>
      {!compact && (
        <span className="projection-note">
          Arithmetic estimate with no new receipts.
        </span>
      )}
    </div>
  );
}
