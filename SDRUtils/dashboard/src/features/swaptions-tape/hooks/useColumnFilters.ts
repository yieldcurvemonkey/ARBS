// Hook for managing column filters with URL sync
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 3796-3803, 3821-3830, 3936-3994)

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import { FilterOperator } from 'primereact/api';
import type { DataTableFilterMeta } from 'primereact/datatable';

export interface UseColumnFiltersReturn {
  filters: DataTableFilterMeta;
  setFilters: (filters: DataTableFilterMeta) => void;
  columnFilterOperator: FilterOperator;
  setColumnFilterOperator: (operator: FilterOperator) => void;
  columnFilterPayload: string;
  columnFilterPayloadKey: string;
  clearFilters: () => void;
}

/**
 * Manages column filter state with URL synchronization
 * Reads filters from URL params on mount, writes on change
 *
 * @returns Filter state and control functions
 */
export function useColumnFilters(): UseColumnFiltersReturn {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [filters, setFilters] = useState<DataTableFilterMeta>({});
  const [columnFilterOperator, setColumnFilterOperator] = useState<FilterOperator>(
    FilterOperator.AND
  );

  // TODO: Extract buildColumnFilterPayload from lines 746-775
  const columnFilterPayload = useMemo(() => {
    return JSON.stringify(filters);
  }, [filters]);

  // TODO: Extract proper payload key generation
  const columnFilterPayloadKey = useMemo(() => {
    return Object.keys(filters).length > 0 ? columnFilterPayload : '';
  }, [columnFilterPayload, filters]);

  const columnFilterPayloadKeyRef = useRef(columnFilterPayloadKey);
  const columnFilterOperatorRef = useRef(columnFilterOperator);

  // Sync refs with current values
  useEffect(() => {
    columnFilterPayloadKeyRef.current = columnFilterPayloadKey;
    columnFilterOperatorRef.current = columnFilterOperator;
  }, [columnFilterPayloadKey, columnFilterOperator]);

  // Read filters from URL on mount/searchParams change
  useEffect(() => {
    const rawFilters = searchParams.get('columnFilters');
    const rawOperator = searchParams.get('columnFilterOp');

    if (rawFilters) {
      try {
        const parsed = JSON.parse(rawFilters);
        setFilters(parsed);
      } catch {
        // Invalid JSON, ignore
      }
    }

    if (rawOperator) {
      setColumnFilterOperator(
        rawOperator.toLowerCase() === 'or' ? FilterOperator.OR : FilterOperator.AND
      );
    }
  }, [searchParams]);

  // Write filters to URL when they change
  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());

    if (Object.keys(filters).length > 0) {
      params.set('columnFilters', columnFilterPayload);
      params.set('columnFilterOp', columnFilterOperator === FilterOperator.OR ? 'or' : 'and');
    } else {
      params.delete('columnFilters');
      params.delete('columnFilterOp');
    }

    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }, [filters, columnFilterOperator, columnFilterPayload, pathname, router, searchParams]);

  const clearFilters = useCallback(() => {
    setFilters({});
    setColumnFilterOperator(FilterOperator.AND);
  }, []);

  return {
    filters,
    setFilters,
    columnFilterOperator,
    setColumnFilterOperator,
    columnFilterPayload,
    columnFilterPayloadKey,
    clearFilters,
  };
}
