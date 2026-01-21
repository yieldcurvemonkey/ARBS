// Hook for managing trade tape data fetching and state
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 3791-3915, 4160-4188)

import { useCallback, useEffect, useRef, useState } from 'react';
import type { TapeRow, TapeResponse } from '../types';

export interface UseTradeTapeDataParams {
  filter: string;
  columnFilterPayloadKey: string;
  columnFilterOperator: string;
}

export interface UseTradeTapeDataReturn {
  rows: TapeRow[];
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  nextCursor: string | null;
  hasMore: boolean;
  sortField: string;
  sortOrder: 1 | -1 | 0;
  fetchTape: (options?: { cursor?: string; since?: string; replace?: boolean }) => Promise<void>;
  setSortField: (field: string) => void;
  setSortOrder: (order: 1 | -1 | 0) => void;
}

/**
 * Manages trade tape data fetching with cursor-based pagination
 * Includes polling for new data and auto-load functionality
 *
 * @param params - Filter and configuration parameters
 * @returns Trade tape data and control functions
 */
export function useTradeTapeData(params: UseTradeTapeDataParams): UseTradeTapeDataReturn {
  const { filter, columnFilterPayloadKey, columnFilterOperator } = params;

  const [rows, setRows] = useState<TapeRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [sortField, setSortField] = useState('execution_start');
  const [sortOrder, setSortOrder] = useState<1 | -1 | 0>(-1);

  const latestRef = useRef<string | null>(null);
  const fetchInFlight = useRef(false);

  const upsertRows = useCallback((incoming: TapeRow[], replace: boolean) => {
    // TODO: Extract upsert logic from lines 3832-3849
    if (replace) {
      setRows(incoming);
    } else {
      setRows((prev) => {
        const map = new Map(prev.map((r) => [r.package_id, r]));
        incoming.forEach((r) => map.set(r.package_id, r));
        return Array.from(map.values());
      });
    }
  }, []);

  const fetchTape = useCallback(
    async (options?: { cursor?: string; since?: string; replace?: boolean }) => {
      // TODO: Extract full fetch logic from lines 3851-3915
      if (fetchInFlight.current) return;
      fetchInFlight.current = true;

      try {
        const { cursor, since, replace = false } = options || {};
        const isCursor = !!cursor;

        if (!isCursor) setLoading(true);
        else setLoadingMore(true);
        setError(null);

        const params = new URLSearchParams();
        if (cursor) params.set('cursor', cursor);
        if (since) params.set('since', since);
        if (filter) params.set('filter', filter);
        if (columnFilterPayloadKey) {
          params.set('columnFilters', columnFilterPayloadKey);
          params.set('columnFilterOp', columnFilterOperator);
        }

        const res = await fetch(`/api/swaptions-tape?${params}`);
        if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`);

        const data: TapeResponse = await res.json();

        upsertRows(data.rows, replace);
        setNextCursor(data.nextCursor);
        setHasMore(data.hasMore);
        if (data.latestExecutionStart) {
          latestRef.current = data.latestExecutionStart;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
        setLoadingMore(false);
        fetchInFlight.current = false;
      }
    },
    [filter, columnFilterPayloadKey, columnFilterOperator, upsertRows]
  );

  // Initial fetch
  useEffect(() => {
    fetchTape({ replace: true });
  }, [fetchTape]);

  // TODO: Add polling logic (lines 4166-4173)
  // TODO: Add auto-load logic (lines 4175-4188)

  return {
    rows,
    loading,
    loadingMore,
    error,
    nextCursor,
    hasMore,
    sortField,
    sortOrder,
    fetchTape,
    setSortField,
    setSortOrder,
  };
}
