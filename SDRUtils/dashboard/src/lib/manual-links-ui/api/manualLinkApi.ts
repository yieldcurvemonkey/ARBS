// ABOUTME: Typed fetch wrapper for the manual-links REST surface. The
// `basePath` parameter lets the same client serve multiple consumers
// (e.g. /api/swaption/links, /api/usd-swaps-tape-v2/links, etc.) since
// the route handlers all chain back to the same shared sofr handler.

import type {
  ManualLinkDetailBundle,
  ManualLinkValidationItem,
} from '../types';

export type CreateLinkBody = {
  trade_ids: string[];
  package_type?: string | null;
  link_reason?: string | null;
  comment?: string | null;
  user_comment?: string | null;
  tags?: string[] | null;
  created_by: string;
  user?: string;
  manual_package_id?: string;
};

export type UpdateLinkBody = {
  package_type?: string | null;
  link_reason?: string | null;
  user_comment?: string | null;
  comment?: string | null;
  tags?: string[] | null;
  add_trades?: string[];
  remove_trades?: string[];
  user?: string;
};

export type ListLinksQuery = {
  limit?: number;
  offset?: number;
  is_active?: boolean;
  manual_package_id?: string;
  created_by?: string;
  tag?: string;
};

export interface ManualLinkApiClient {
  createLink(body: CreateLinkBody): Promise<{ link_id: string; manual_package_id: string }>;
  validateLink(body: CreateLinkBody): Promise<{
    validation: ManualLinkValidationItem[];
    metrics: Record<string, unknown> | null;
  }>;
  getLinkDetail(linkId: string): Promise<ManualLinkDetailBundle>;
  updateLink(
    linkId: string,
    body: UpdateLinkBody,
    adminPassword: string,
  ): Promise<{ link_id: string }>;
  deactivateLink(linkId: string, adminPassword: string, reason?: string): Promise<void>;
  listLinks(query?: ListLinksQuery): Promise<{ items: unknown[] }>;
}

async function parseError(res: Response): Promise<Error> {
  try {
    const payload = await res.json();
    if (payload && typeof payload === 'object' && 'error' in payload && payload.error) {
      return new Error(String((payload as { error: unknown }).error));
    }
  } catch {
    // ignore
  }
  return new Error(`Request failed with status ${res.status}`);
}

function buildQueryString(query: Record<string, unknown>): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    params.set(key, String(value));
  });
  const s = params.toString();
  return s ? `?${s}` : '';
}

export function createManualLinkApi(basePath: string): ManualLinkApiClient {
  return {
    async createLink(body) {
      const res = await fetch(basePath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body }),
      });
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as { link_id: string; manual_package_id: string };
    },
    async validateLink(body) {
      const res = await fetch(basePath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, validate_only: true }),
      });
      if (!res.ok) {
        // Validation endpoints often return 4xx with a payload; surface
        // the error.
        throw await parseError(res);
      }
      const payload = await res.json();
      return {
        validation: (payload?.validation as ManualLinkValidationItem[]) ?? [],
        metrics: (payload?.metrics as Record<string, unknown>) ?? null,
      };
    },
    async getLinkDetail(linkId) {
      const res = await fetch(`${basePath}/${encodeURIComponent(linkId)}`);
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as ManualLinkDetailBundle;
    },
    async updateLink(linkId, body, adminPassword) {
      const res = await fetch(`${basePath}/${encodeURIComponent(linkId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, admin_password: adminPassword || undefined }),
      });
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as { link_id: string };
    },
    async deactivateLink(linkId, adminPassword, reason) {
      const res = await fetch(`${basePath}/${encodeURIComponent(linkId)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          admin_password: adminPassword || undefined,
          reason: reason || undefined,
        }),
      });
      if (!res.ok) throw await parseError(res);
    },
    async listLinks(query) {
      const url = `${basePath}${query ? buildQueryString(query as Record<string, unknown>) : ''}`;
      const res = await fetch(url);
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as { items: unknown[] };
    },
  };
}
