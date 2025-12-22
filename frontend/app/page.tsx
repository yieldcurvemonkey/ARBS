"use client";

import { useMemo, useState } from "react";

import { ChartGrid, ChartWidget } from "@/components/ChartGrid";
import { SeriesPicker } from "@/components/SeriesPicker";
import { requestTimeseries } from "@/lib/fetchTimeseries";
import { listCatalog } from "@/lib/sampleCatalog";
import { Frequency, TimeseriesSeries } from "@/lib/types";

function formatInputDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function randomId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

const defaultEnd = new Date();
const defaultStart = new Date();
defaultStart.setDate(defaultEnd.getDate() - 180);

export default function Home() {
  const [start, setStart] = useState(formatInputDate(defaultStart));
  const [end, setEnd] = useState(formatInputDate(defaultEnd));
  const [selectedSeries, setSelectedSeries] = useState<string[]>(["IRS_5Y_PAR", "FRB_10Y_TSY"]);
  const [frequency, setFrequency] = useState<Frequency>("D");
  const [title, setTitle] = useState("IRS + Treasury overlay");
  const [widgets, setWidgets] = useState<ChartWidget[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const catalog = useMemo(() => listCatalog(), []);

  const handleAddChart = async () => {
    if (!selectedSeries.length) {
      setError("Select at least one series to add a chart.");
      return;
    }
    setLoading(true);
    setError(null);

    try {
      const response = await requestTimeseries({
        seriesIds: selectedSeries,
        start,
        end,
        frequency,
      });

      const newWidget: ChartWidget = {
        id: randomId(),
        title: title.trim() ||
          catalog
            .filter((c) => selectedSeries.includes(c.id))
            .map((c) => c.label)
            .join(" | "),
        series: response.series as TimeseriesSeries[],
      };

      setWidgets((prev) => [...prev, newWidget]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fetch timeseries");
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = (id: string) => setWidgets((prev) => prev.filter((w) => w.id !== id));

  return (
    <main className="main-shell">
      <header>
        <div>
          <h1>Timeseries layout lab</h1>
          <p>
            Build custom dashboards that mirror the fetching patterns from the ARBS notebooks. Drag,
            resize, and mix IRS, bond, and STIR futures curves on a flexible grid.
          </p>
        </div>
        <div className="panel" style={{ minWidth: 260 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>Layout tips</div>
          <ul style={{ margin: 0, paddingLeft: 18, color: "#cbd5e1" }}>
            <li>Drag chart headers to rearrange.</li>
            <li>Resize panels from the bottom-right grip.</li>
            <li>Layer multiple series in one widget or spread them across tiles.</li>
          </ul>
        </div>
      </header>

      <div className="control-grid" style={{ marginBottom: 16 }}>
        <label>
          Start date
          <input
            className="input"
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          End date
          <input className="input" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          Chart title
          <input
            className="input"
            type="text"
            value={title}
            placeholder="Optional custom label"
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
      </div>

      <SeriesPicker
        selected={selectedSeries}
        onChange={setSelectedSeries}
        frequency={frequency}
        onFrequencyChange={setFrequency}
      />

      <div style={{ marginTop: 16 }}>
        <button type="button" onClick={handleAddChart} disabled={loading}>
          {loading ? "Loading series…" : "Add chart to layout"}
        </button>
        {error ? <div style={{ color: "#fb7185", marginTop: 8 }}>{error}</div> : null}
        <div className="footer-note">
          Data is generated locally based on the timeseries builder examples so you can experiment
          with layout ideas without a live curve server.
        </div>
      </div>

      <div style={{ marginTop: 24 }}>
        {widgets.length === 0 ? (
          <div className="panel chart-empty" style={{ minHeight: 200 }}>
            Add a chart to start crafting your custom notebook-inspired layout.
          </div>
        ) : (
          <ChartGrid widgets={widgets} onRemove={handleRemove} />
        )}
      </div>
    </main>
  );
}
