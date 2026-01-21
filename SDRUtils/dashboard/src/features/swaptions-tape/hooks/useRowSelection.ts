// Hook for managing row selection with auto-cleanup
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 3811, 3936-3942)

import { useEffect, useState } from 'react';
import type { TapeRow } from '../types';

export interface UseRowSelectionParams {
  rows: TapeRow[];
}

export interface UseRowSelectionReturn {
  selectedRows: TapeRow[];
  setSelectedRows: (rows: TapeRow[]) => void;
}

/**
 * Manages row selection with automatic cleanup
 * Removes selected rows that are no longer in the data
 *
 * @param params - Current rows
 * @returns Selected rows and setter function
 */
export function useRowSelection(params: UseRowSelectionParams): UseRowSelectionReturn {
  const { rows } = params;
  const [selectedRows, setSelectedRows] = useState<TapeRow[]>([]);

  // Auto-cleanup: Remove selected rows that are no longer in the data
  useEffect(() => {
    if (selectedRows.length > 0) {
      const currentIds = new Set(rows.map((r) => r.package_id));
      const filtered = selectedRows.filter((r) => currentIds.has(r.package_id));
      if (filtered.length !== selectedRows.length) {
        setSelectedRows(filtered);
      }
    }
  }, [rows, selectedRows]);

  return {
    selectedRows,
    setSelectedRows,
  };
}
