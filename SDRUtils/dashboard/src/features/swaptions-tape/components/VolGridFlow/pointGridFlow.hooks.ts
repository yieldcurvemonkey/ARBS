import { useEffect, useMemo, useRef, useState } from "react";
import type {
  PointGridFlowResponse,
  PointGridPlatform,
} from "./pointGridFlow.types";

type PointGridFlowParams = {
  platform: PointGridPlatform;
  asOfDate?: string;
  excludeLargeCustyNotional: boolean;
};

type PointGridFlowState = {
  data: PointGridFlowResponse | null;
  isLoading: boolean;
  error: Error | null;
};

type CacheEntry = {
  data: PointGridFlowResponse;
  timestamp: number;
};

const pointGridCache = new Map<string, CacheEntry>();

export function usePointGridFlow(params: PointGridFlowParams): PointGridFlowState {
  const { platform, asOfDate, excludeLargeCustyNotional } = params;
  const [data, setData] = useState<PointGridFlowResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const inFlightRef = useRef<string | null>(null);

  const cacheKey = useMemo(
    () =>
      JSON.stringify({
        platform,
        asOfDate: asOfDate || null,
        excludeLargeCustyNotional: !!excludeLargeCustyNotional,
      }),
    [asOfDate, excludeLargeCustyNotional, platform],
  );

  useEffect(() => {
    const cached = pointGridCache.get(cacheKey);
    if (cached) {
      setData(cached.data);
    }

    if (inFlightRef.current === cacheKey) return;
    inFlightRef.current = cacheKey;

    const controller = new AbortController();
    const fetchPointGridFlow = async () => {
      setIsLoading(!cached);
      setError(null);
      try {
        const searchParams = new URLSearchParams();
        searchParams.set("platform", platform);
        if (asOfDate) {
          searchParams.set("asOfDate", asOfDate);
        }
        if (excludeLargeCustyNotional) {
          searchParams.set("excludeLargeCustyNotional", "true");
        }
        const response = await fetch(
          `/api/swaptions-tape/point-grid-flow?${searchParams.toString()}`,
          { signal: controller.signal },
        );
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || "Failed to load point-grid flow.");
        }
        const payload = (await response.json()) as PointGridFlowResponse;
        pointGridCache.set(cacheKey, { data: payload, timestamp: Date.now() });
        setData(payload);
      } catch (fetchError) {
        if ((fetchError as any)?.name === "AbortError") return;
        setError(
          fetchError instanceof Error
            ? fetchError
            : new Error("Failed to load point-grid flow."),
        );
      } finally {
        setIsLoading(false);
        if (inFlightRef.current === cacheKey) {
          inFlightRef.current = null;
        }
      }
    };

    fetchPointGridFlow();

    return () => {
      controller.abort();
      if (inFlightRef.current === cacheKey) {
        inFlightRef.current = null;
      }
    };
  }, [asOfDate, cacheKey, excludeLargeCustyNotional, platform]);

  return { data, isLoading, error };
}
