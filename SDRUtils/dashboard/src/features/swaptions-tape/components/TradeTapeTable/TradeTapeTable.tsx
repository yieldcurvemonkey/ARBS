// Main trade tape DataTable component
// TODO: Extract full implementation from SwaptionTradeTape.tsx

"use client";

import { DataTable } from 'primereact/datatable';
import { Column } from 'primereact/column';
import type { TapeRow } from '../../types';

export interface TradeTapeTableProps {
  rows: TapeRow[];
  loading: boolean;
  selectedRows: TapeRow[];
  expandedRows: Record<string, boolean>;
  onSelectionChange: (rows: TapeRow[]) => void;
  onRowExpand: (row: TapeRow) => void;
  onRowCollapse: (row: TapeRow) => void;
  onSort?: (event: any) => void;
  sortField?: string;
  sortOrder?: number;
}

/**
 * Trade tape table with expandable rows and column filtering
 * Wraps PrimeReact DataTable with custom styling and functionality
 */
export function TradeTapeTable(props: TradeTapeTableProps) {
  const {
    rows,
    loading,
    selectedRows,
    expandedRows,
    onSelectionChange,
    onRowExpand,
    onRowCollapse,
    onSort,
    sortField,
    sortOrder,
  } = props;

  // TODO: Extract column definitions from SwaptionTradeTape.tsx
  // TODO: Extract row expansion template
  // TODO: Extract cell body templates for custom rendering
  // TODO: Extract package-specific styling logic

  return (
    <div className="trade-tape-table">
      <DataTable
        value={rows}
        loading={loading}
        selection={selectedRows}
        onSelectionChange={(e) => onSelectionChange(e.value)}
        expandedRows={expandedRows}
        onRowToggle={(e) => {
          // Handle row expansion
        }}
        dataKey="package_id"
        sortField={sortField}
        sortOrder={sortOrder}
        onSort={onSort}
        scrollable
        scrollHeight="flex"
        virtualScrollerOptions={{ itemSize: 44 }}
        className="p-datatable-sm"
      >
        {/* TODO: Add Column components with proper templates */}
        <Column selectionMode="multiple" headerStyle={{ width: '3rem' }} />
        <Column field="event_action" header="Action" sortable />
        <Column field="package_type" header="Package Type" sortable />
        <Column field="execution_start" header="Time" sortable />
        <Column field="total_notional" header="Notional" sortable />
      </DataTable>
    </div>
  );
}
