// ABOUTME: React hook over manualLinkApi.getLinkDetail. Auto-fetches the
// link detail when linkId changes and exposes loading / error / detail
// state plus a refetch handle. When linkId is null the hook stays idle
// and never fires a request - this matches the modal-open lifecycle
// (linkId is set when the modal opens).

import { useCallback, useEffect, useState } from 'react';
import { createManualLinkApi } from '../api/manualLinkApi';
import type { ManualLinkDetailBundle } from '../types';

export interface UseManualLinkDetailsOptions {
  linkId: string | null;
  basePath: string;
}

export interface UseManualLinkDetailsState {
  detail: ManualLinkDetailBundle | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useManualLinkDetails(
  options: UseManualLinkDetailsOptions,
): UseManualLinkDetailsState {
  const { linkId, basePath } = options;
  const [detail, setDetail] = useState<ManualLinkDetailBundle | null>(null);
  const [loading, setLoading] = useState<boolean>(linkId !== null);
  const [error, setError] = useState<string | null>(null);

  const fetcher = useCallback(async () => {
    if (!linkId) {
      setLoading(false);
      setDetail(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const api = createManualLinkApi(basePath);
      const bundle = await api.getLinkDetail(linkId);
      setDetail(bundle);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load manual link.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [basePath, linkId]);

  useEffect(() => {
    void fetcher();
  }, [fetcher]);

  const refetch = useCallback(() => {
    void fetcher();
  }, [fetcher]);

  return { detail, loading, error, refetch };
}
