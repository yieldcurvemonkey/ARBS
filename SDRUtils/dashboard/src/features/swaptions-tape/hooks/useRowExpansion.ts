// Hook for managing expandable rows
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 3808-3810, 4254-4266)

import { useCallback, useState } from 'react';
import type { TapeRow } from '../types';

export interface UseRowExpansionReturn {
  expandedRows: Record<string, boolean>;
  setExpandedRows: (rows: Record<string, boolean>) => void;
  toggleRowExpansion: (row: TapeRow) => void;
}

/**
 * Manages row expansion state for expandable table rows
 *
 * @returns Expansion state and control functions
 */
export function useRowExpansion(): UseRowExpansionReturn {
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  const toggleRowExpansion = useCallback((row: TapeRow) => {
    setExpandedRows((prev) => ({
      ...prev,
      [row.package_id]: !prev[row.package_id],
    }));
  }, []);

  return {
    expandedRows,
    setExpandedRows,
    toggleRowExpansion,
  };
}
