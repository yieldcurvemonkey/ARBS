// Trade tape filter controls
// TODO: Extract full implementation from SwaptionTradeTape.tsx

"use client";

import type { DataTableFilterMeta } from 'primereact/datatable';

export interface TradeTapeFiltersProps {
  globalFilter: string;
  onGlobalFilterChange: (value: string) => void;
  columnFilters: DataTableFilterMeta;
  onColumnFiltersChange: (filters: DataTableFilterMeta) => void;
  columnFilterOperator: string;
  onColumnFilterOperatorChange: (operator: string) => void;
  onClearFilters: () => void;
}

/**
 * Filter controls for the trade tape table
 * Includes global search and column-specific filters
 */
export function TradeTapeFilters(props: TradeTapeFiltersProps) {
  const {
    globalFilter,
    onGlobalFilterChange,
    columnFilters,
    onColumnFiltersChange,
    columnFilterOperator,
    onColumnFilterOperatorChange,
    onClearFilters,
  } = props;

  // TODO: Extract global filter input
  // TODO: Extract column filter UI
  // TODO: Extract saved filters functionality
  // TODO: Extract filter operator toggle (AND/OR)

  return (
    <div className="flex flex-col gap-4 mb-4">
      {/* Global Search */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={globalFilter}
          onChange={(e) => onGlobalFilterChange(e.target.value)}
          placeholder="Search trades..."
          className="flex-1 px-4 py-2 bg-gray-800 border border-gray-700 rounded text-white"
        />
        <button
          onClick={onClearFilters}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded"
        >
          Clear Filters
        </button>
      </div>

      {/* TODO: Add column filters UI */}
      {/* TODO: Add saved filters dropdown */}
    </div>
  );
}
