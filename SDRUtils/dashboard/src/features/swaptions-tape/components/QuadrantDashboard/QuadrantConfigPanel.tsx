// Configurable quadrant boundaries and desk commentary editor
import { memo, useState, useCallback } from 'react';
import type { QuadrantConfig, QuadrantMeta, VolGridQuadrant } from '../../types/quadrant.types';
import { QUADRANT_COLORS } from '../../quadrant/quadrant.config';

export type QuadrantConfigPanelProps = {
  config: QuadrantConfig;
  onConfigChange: (config: QuadrantConfig) => void;
  meta: Record<VolGridQuadrant, QuadrantMeta>;
  onMetaChange: (quadrant: VolGridQuadrant, updates: Partial<QuadrantMeta>) => void;
  onClose: () => void;
};

export const QuadrantConfigPanel = memo(function QuadrantConfigPanel({
  config,
  onConfigChange,
  meta,
  onMetaChange,
  onClose,
}: QuadrantConfigPanelProps) {
  const [localConfig, setLocalConfig] = useState(config);
  const [editingQuadrant, setEditingQuadrant] = useState<VolGridQuadrant | null>(null);

  const handleBoundaryChange = useCallback(
    (field: keyof QuadrantConfig, value: string) => {
      const num = parseFloat(value);
      if (!Number.isFinite(num) || num < 0) return;
      setLocalConfig((prev) => ({ ...prev, [field]: num }));
    },
    [],
  );

  const applyConfig = useCallback(() => {
    onConfigChange(localConfig);
  }, [localConfig, onConfigChange]);

  const quadrants: VolGridQuadrant[] = ['ULC', 'URC', 'LLC', 'LRC'];

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/80 p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-200">Quadrant Configuration</span>
        <button
          onClick={onClose}
          className="text-slate-500 hover:text-slate-300 text-[11px]"
        >
          Close
        </button>
      </div>

      {/* Boundary configuration */}
      <div className="border border-slate-800 rounded p-3 space-y-2">
        <div className="text-[11px] text-slate-400 font-medium">Boundary Settings</div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-[10px] text-slate-500 mb-1">
              Expiry Boundary (years)
            </label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              max="10"
              value={localConfig.expiryBoundaryYears}
              onChange={(e) => handleBoundaryChange('expiryBoundaryYears', e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300"
            />
            <div className="text-[9px] text-slate-600 mt-0.5">Between gamma/vega</div>
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 mb-1">
              Tenor Boundary (years)
            </label>
            <input
              type="number"
              step="0.5"
              min="1"
              max="20"
              value={localConfig.tenorBoundaryYears}
              onChange={(e) => handleBoundaryChange('tenorBoundaryYears', e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300"
            />
            <div className="text-[9px] text-slate-600 mt-0.5">Between short/long tails</div>
          </div>
          <div>
            <label className="block text-[10px] text-slate-500 mb-1">
              Boundary Tolerance (years)
            </label>
            <input
              type="number"
              step="0.25"
              min="0"
              max="3"
              value={localConfig.boundaryToleranceYears}
              onChange={(e) => handleBoundaryChange('boundaryToleranceYears', e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300"
            />
            <div className="text-[9px] text-slate-600 mt-0.5">Width of boundary zone</div>
          </div>
        </div>
        <button
          onClick={applyConfig}
          className="text-[10px] bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-1 rounded mt-1"
        >
          Apply Boundaries
        </button>
      </div>

      {/* Quadrant commentary editor */}
      <div className="border border-slate-800 rounded p-3 space-y-2">
        <div className="text-[11px] text-slate-400 font-medium">Desk Commentary</div>
        <div className="grid grid-cols-4 gap-2">
          {quadrants.map((q) => {
            const colors = QUADRANT_COLORS[q];
            const m = meta[q];
            return (
              <button
                key={q}
                onClick={() => setEditingQuadrant(editingQuadrant === q ? null : q)}
                className={`${colors.bg} ${colors.border} border rounded p-2 text-left ${
                  editingQuadrant === q ? 'ring-1 ring-slate-500' : ''
                }`}
              >
                <div className={`${colors.text} font-semibold text-[11px]`}>{q}</div>
                <div className="text-slate-500 text-[10px] truncate">{m.deskView}</div>
              </button>
            );
          })}
        </div>

        {/* Editing form for selected quadrant */}
        {editingQuadrant != null && (
          <QuadrantMetaEditor
            quadrant={editingQuadrant}
            meta={meta[editingQuadrant as VolGridQuadrant]}
            onChange={(updates) => onMetaChange(editingQuadrant as VolGridQuadrant, updates)}
          />
        )}
      </div>
    </div>
  );
});

/** Editor for a single quadrant's desk commentary */
const QuadrantMetaEditor = memo(function QuadrantMetaEditor({
  quadrant,
  meta,
  onChange,
}: {
  quadrant: VolGridQuadrant;
  meta: QuadrantMeta;
  onChange: (updates: Partial<QuadrantMeta>) => void;
}) {
  const colors = QUADRANT_COLORS[quadrant];

  return (
    <div className={`border ${colors.border} rounded p-3 space-y-2 mt-2`}>
      <div className={`${colors.text} font-semibold text-[11px]`}>
        {quadrant} — {meta.fullName}
      </div>

      <div>
        <label className="block text-[10px] text-slate-500 mb-0.5">Desk View</label>
        <input
          type="text"
          value={meta.deskView}
          onChange={(e) => onChange({ deskView: e.target.value, deskViewUpdatedAt: new Date().toISOString() })}
          className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300"
        />
      </div>

      <div>
        <label className="block text-[10px] text-slate-500 mb-0.5">Supply/Demand Drivers</label>
        <textarea
          value={meta.supplyDemandDrivers}
          onChange={(e) => onChange({ supplyDemandDrivers: e.target.value })}
          rows={2}
          className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300 resize-none"
        />
      </div>

      <div>
        <label className="block text-[10px] text-slate-500 mb-0.5">
          Typical Participants (comma-separated)
        </label>
        <input
          type="text"
          value={meta.typicalParticipants.join(', ')}
          onChange={(e) =>
            onChange({
              typicalParticipants: e.target.value
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-300"
        />
      </div>

      <div className="text-[9px] text-slate-600">
        Last updated: {meta.deskViewUpdatedAt ? new Date(meta.deskViewUpdatedAt).toLocaleString() : 'N/A'}{' '}
        by {meta.deskViewUpdatedBy || 'SYSTEM'}
      </div>
    </div>
  );
});
