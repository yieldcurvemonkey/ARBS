"use client";

import { useMemo } from "react";

import { listCatalog } from "@/lib/sampleCatalog";
import { Frequency, TimeseriesCatalogEntry } from "@/lib/types";

interface Props {
  selected: string[];
  onChange: (next: string[]) => void;
  frequency: Frequency;
  onFrequencyChange: (frequency: Frequency) => void;
}

export function SeriesPicker({ selected, onChange, frequency, onFrequencyChange }: Props) {
  const catalog = useMemo(() => listCatalog(), []);

  const toggle = (id: string) => {
    if (selected.includes(id)) {
      onChange(selected.filter((item) => item !== id));
    } else {
      onChange([...selected, id]);
    }
  };

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0, marginBottom: 12 }}>Select series</h2>
      <p style={{ marginTop: 0, marginBottom: 16 }}>
        Curated examples mirror the timeseries builder notebooks—swap ladders, bond benchmarks, and
        STIR futures.
      </p>
      <div className="chip-group">
        {catalog.map((entry: TimeseriesCatalogEntry) => (
          <button
            key={entry.id}
            type="button"
            className={`chip ${selected.includes(entry.id) ? "selected" : ""}`}
            onClick={() => toggle(entry.id)}
          >
            <div style={{ fontWeight: 700 }}>{entry.label}</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{entry.description}</div>
          </button>
        ))}
      </div>

      <div className="control-grid" style={{ marginTop: 20 }}>
        <label>
          Sampling frequency
          <select
            value={frequency}
            onChange={(e) => onFrequencyChange(e.target.value as Frequency)}
            aria-label="Frequency"
          >
            <option value="D">Daily</option>
            <option value="W">Weekly</option>
            <option value="M">Monthly</option>
          </select>
        </label>
      </div>
    </div>
  );
}
