"use client";

import { Responsive, WidthProvider } from "react-grid-layout";

import { TimeseriesChart } from "./TimeseriesChart";
import { TimeseriesSeries } from "@/lib/types";

const ResponsiveGrid = WidthProvider(Responsive);
const palette = ["#38bdf8", "#a78bfa", "#22d3ee", "#fbbf24", "#fb7185", "#f472b6"];

export interface ChartWidget {
  id: string;
  title: string;
  series: TimeseriesSeries[];
}

interface Props {
  widgets: ChartWidget[];
  onRemove: (id: string) => void;
}

export function ChartGrid({ widgets, onRemove }: Props) {
  const makeLayout = () => widgets.map((w, idx) => ({ i: w.id, x: (idx * 4) % 12, y: Infinity, w: 4, h: 10 }));
  const layouts = {
    lg: makeLayout(),
    md: makeLayout(),
    sm: makeLayout(),
    xs: makeLayout(),
    xxs: makeLayout(),
  };

  return (
    <ResponsiveGrid
      className="layout"
      layouts={layouts}
      cols={{ lg: 12, md: 10, sm: 6, xs: 4, xxs: 2 }}
      rowHeight={28}
      draggableHandle=".chart-header"
      margin={[12, 12]}
      isBounded
    >
      {widgets.map((widget) => (
        <div key={widget.id} data-grid={{ i: widget.id }} className="panel grid-card">
          <div className="chart-header">
            <h3>{widget.title}</h3>
            <button type="button" onClick={() => onRemove(widget.id)} style={{ width: "auto" }}>
              Remove
            </button>
          </div>
          <TimeseriesChart series={widget.series} />
          <div className="legend">
            {widget.series.map((s, idx) => (
              <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span className="legend-swatch" style={{ background: palette[idx % palette.length] }} />
                <span>{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </ResponsiveGrid>
  );
}
