import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Snapshot, stamp } from "./api";
export default function MetricChart({
  series,
}: {
  series: Snapshot["series"][number];
}) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={series.points} accessibilityLayer>
          <XAxis
            dataKey="at"
            tickFormatter={(v) =>
              new Date(v).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })
            }
            minTickGap={50}
          />
          <YAxis width={42} />
          <Tooltip labelFormatter={(v) => stamp(v)} />
          <Line
            type="linear"
            dataKey="value"
            stroke="#244fb2"
            dot={false}
            strokeWidth={2}
            connectNulls={false}
            isAnimationActive={false}
          />
          {series.guardrail !== null && (
            <ReferenceLine
              y={series.guardrail}
              stroke="#b53b3b"
              strokeDasharray="4 4"
              label="Guardrail"
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
