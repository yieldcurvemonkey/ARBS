"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { TimeseriesSeries } from "@/lib/types";

const palette = ["#38bdf8", "#a78bfa", "#22d3ee", "#fbbf24", "#fb7185", "#f472b6"];

interface Props {
  series: TimeseriesSeries[];
  height?: number;
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString();
}

export function TimeseriesChart({ series, height = 260 }: Props) {
  if (!series.length || series.every((s) => s.points.length === 0)) {
    return <div className="chart-empty">No data returned for this request.</div>;
  }

  const combined = series.flatMap((s) => s.points.map((p) => ({ ...p, series: s.id })));
  const data = Object.values(
    combined.reduce<Record<string, Record<string, string | number>>>(
      (acc, point) => {
        const existing = acc[point.date] || { date: point.date };
        existing[point.series] = point.value;
        acc[point.date] = existing;
        return acc;
      },
      {},
    ),
  ).sort((a, b) => (a.date > b.date ? 1 : -1));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 24, left: 0, bottom: 4 }}>
        <CartesianGrid stroke="#1f2937" strokeDasharray="3 3" />
        <XAxis dataKey="date" stroke="#94a3b8" tickFormatter={formatDate} minTickGap={32} />
        <YAxis stroke="#94a3b8" />
        <Tooltip contentStyle={{ background: "#0b1224", border: "1px solid #1f2937" }} />
        <Legend />
        {series.map((s, idx) => (
          <Line
            key={s.id}
            type="monotone"
            dataKey={s.id}
            stroke={palette[idx % palette.length]}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            name={s.label}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
