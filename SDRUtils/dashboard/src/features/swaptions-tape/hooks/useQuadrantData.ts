// Hook for computing quadrant flow state from trade tape data
import { useMemo, useState, useCallback } from 'react';
import type { TapeRow } from '../types/trade.types';
import type {
  QuadrantConfig,
  GridFlowState,
  VolGridQuadrant,
  QuadrantAnomaly,
  QuadrantMeta,
  TradeQuadrantContext,
  QuadrantClassification,
} from '../types/quadrant.types';
import {
  computeGridFlowState,
  classifyTradeQuadrant,
  detectQuadrantAnomalies,
  buildTradeQuadrantContext,
} from '../quadrant/quadrant.utils';
import { DEFAULT_QUADRANT_CONFIG, DEFAULT_QUADRANT_META } from '../quadrant/quadrant.config';

export type UseQuadrantDataParams = {
  /** All visible trades in the tape */
  rows: TapeRow[];
  /** Optional custom config overrides */
  initialConfig?: Partial<QuadrantConfig>;
};

export type UseQuadrantDataReturn = {
  /** Full grid flow state */
  gridState: GridFlowState;
  /** Current quadrant config */
  config: QuadrantConfig;
  /** Update config boundaries */
  setConfig: (config: QuadrantConfig) => void;
  /** Quadrant metadata (desk commentary, editable) */
  meta: Record<VolGridQuadrant, QuadrantMeta>;
  /** Update metadata for a quadrant */
  updateMeta: (quadrant: VolGridQuadrant, updates: Partial<QuadrantMeta>) => void;
  /** Anomalies detected */
  anomalies: QuadrantAnomaly[];
  /** Classify a single trade */
  classifyTrade: (row: TapeRow) => QuadrantClassification;
  /** Get full quadrant context for a single trade */
  getTradeContext: (row: TapeRow) => TradeQuadrantContext;
  /** Map from package_id to quadrant classification */
  classificationMap: Map<string, QuadrantClassification>;
};

export function useQuadrantData({
  rows,
  initialConfig,
}: UseQuadrantDataParams): UseQuadrantDataReturn {
  const [config, setConfig] = useState<QuadrantConfig>({
    ...DEFAULT_QUADRANT_CONFIG,
    ...initialConfig,
  });

  const [meta, setMeta] = useState<Record<VolGridQuadrant, QuadrantMeta>>({
    ...DEFAULT_QUADRANT_META,
  });

  const updateMeta = useCallback(
    (quadrant: VolGridQuadrant, updates: Partial<QuadrantMeta>) => {
      setMeta((prev) => ({
        ...prev,
        [quadrant]: { ...prev[quadrant], ...updates },
      }));
    },
    [],
  );

  // Pre-compute classification for all rows
  const classificationMap = useMemo(() => {
    const map = new Map<string, QuadrantClassification>();
    for (const row of rows) {
      map.set(row.package_id, classifyTradeQuadrant(row, config));
    }
    return map;
  }, [rows, config]);

  // Compute grid flow state
  const gridState = useMemo(
    () => computeGridFlowState(rows, config),
    [rows, config],
  );

  // Detect anomalies (no historical baselines yet — will be populated when timeseries data is available)
  const anomalies = useMemo(
    () => detectQuadrantAnomalies(gridState),
    [gridState],
  );

  const classifyTrade = useCallback(
    (row: TapeRow) => classifyTradeQuadrant(row, config),
    [config],
  );

  const getTradeContext = useCallback(
    (row: TapeRow) => buildTradeQuadrantContext(row, rows, config, meta),
    [rows, config, meta],
  );

  return {
    gridState,
    config,
    setConfig,
    meta,
    updateMeta,
    anomalies,
    classifyTrade,
    getTradeContext,
    classificationMap,
  };
}
