"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  type ChartPoint,
  firstFutureWeek,
  formatPounds,
  type SeriesPoint,
  toChartData,
} from "@/lib/forecasts";

const COLORS = { actual: "#292524", forecast: "#15803d", band: "#16a34a", lastYear: "#a8a29e" };

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: ChartPoint }[] }) {
  const point = active ? payload?.[0]?.payload : undefined;
  if (!point) return null;
  return (
    <div className="rounded-md border border-stone-200 bg-white p-2 text-xs shadow">
      <p className="font-medium">Week of {point.label}</p>
      {point.actual != null && <p>Actual: {formatPounds(point.actual)}</p>}
      {point.p50 != null && (
        <p className="text-green-800">
          {point.actual == null ? "Forecast" : "Forecast made at the time"}: {formatPounds(point.p50)}
        </p>
      )}
      {point.p10 != null && point.p90 != null && (
        <p className="text-stone-600">
          Range: {formatPounds(point.p10)} to {formatPounds(point.p90)}
        </p>
      )}
      {point.lastYear != null && <p className="text-stone-500">Last year&apos;s value: {formatPounds(point.lastYear)}</p>}
    </div>
  );
}

export function ForecastChart({
  points,
  showLastYear,
  label,
  summaryId,
}: {
  points: SeriesPoint[];
  showLastYear: boolean;
  label: string;
  summaryId?: string;
}) {
  const data = toChartData(points);
  const future = firstFutureWeek(data);
  const futureLabel = data.find((p) => p.weekStart === future)?.label;

  return (
    <div role="img" aria-label={label} aria-describedby={summaryId} className="h-64 w-full sm:h-80">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} accessibilityLayer={false}>
          <CartesianGrid stroke="#e7e5e4" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={24} tickLine={false} />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(v: number) => v.toLocaleString("en-US")}
            width={56}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<ChartTooltip />} />
          <Area
            dataKey="band"
            name="P10 to P90"
            stroke="none"
            fill={COLORS.band}
            fillOpacity={0.18}
            isAnimationActive={false}
            activeDot={false}
          />
          {showLastYear && (
            <Line
              dataKey="lastYear"
              name="Last year's value"
              stroke={COLORS.lastYear}
              strokeDasharray="2 4"
              dot={false}
              isAnimationActive={false}
            />
          )}
          <Line
            dataKey="actual"
            name="Actual"
            stroke={COLORS.actual}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="p50"
            name="Forecast"
            stroke={COLORS.forecast}
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={{ r: 2.5, fill: COLORS.forecast }}
            isAnimationActive={false}
          />
          {futureLabel && (
            <ReferenceLine
              x={futureLabel}
              stroke="#78716c"
              strokeDasharray="3 3"
              label={{ value: "Next week", position: "insideTopRight", fontSize: 11, fill: "#57534e" }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
