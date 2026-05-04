// ABOUTME: Shared manual-link detail modal. Single read+edit component
// with a mode toggle: read mode shows the link record + linked trades +
// metrics + history; edit mode reveals the editable form (package type,
// link reason, tags, comment, add / remove trades) plus a deactivate
// action. Edit submit and deactivate both require the admin password.
// Auto-fetches the link details when opened with a non-null linkId.
//
// Prop contract (kept stable across consumers - swaptions-tape and
// usd-swaps-tape-v2 both target this surface). Per-consumer differences
// (helper functions, constants) flow in via props with sensible
// defaults; the modal does not reach back into either feature module.

import * as React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, X } from 'lucide-react';
import { manualLinkColor } from '../color';
import { ManualLinkValidationList } from './ManualLinkValidationList';
import { ManualLinkMetricsTable } from './ManualLinkMetricsTable';
import { ManualLinkHistoryTable } from './ManualLinkHistoryTable';
import type {
  ManualLinkDetail,
  ManualLinkHistoryItem,
  ManualLinkTrade,
  ManualLinkValidationItem,
} from '../types';

export type Option = { value: string; label: string };

export interface ManualLinkDetailModalProps {
  isOpen: boolean;
  linkId: string | null;
  onClose: () => void;
  onUpdated?: () => void;
  onDeactivated?: (linkId: string) => void;
  /** Base path of the API surface, e.g. `/api/swaption/links` or `/api/usd-swaps-tape-v2/links`. */
  apiBasePath: string;
  /** Bound state for the user input in the form. */
  currentUser: string;
  onUserChange: (value: string) => void;
  /** Bound state for the admin password input. */
  adminPassword: string;
  onAdminPasswordChange: (value: string) => void;
  /** Allowed package_type options for the edit form. */
  packageTypeOptions: Option[];
  /** Allowed link_reason options. */
  linkReasonOptions: Option[];
  /** Per-consumer helpers (with sensible defaults). */
  parseIdList?: (input: string) => string[];
  dedupeTrades?: (trades: ManualLinkTrade[]) => ManualLinkTrade[];
  formatTimestamp?: (iso: string | null | undefined) => string;
  formatNotional?: (value: number | null | undefined) => string;
  formatMetricValue?: (value: unknown) => string;
}

function defaultParseIdList(input: string): string[] {
  return input
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function defaultDedupeTrades(trades: ManualLinkTrade[]): ManualLinkTrade[] {
  const seen = new Set<string>();
  const out: ManualLinkTrade[] = [];
  for (const t of trades) {
    if (seen.has(t.trade_id)) continue;
    seen.add(t.trade_id);
    out.push(t);
  }
  return out;
}

function defaultFormatTimestamp(iso?: string | null): string {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z');
}

function defaultFormatNotional(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return Math.abs(value) >= 1000 ? value.toLocaleString() : String(value);
}

function defaultFormatMetricValue(value: unknown): string {
  if (value === null || value === undefined) return '--';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '--';
    if (Math.abs(value) >= 1000) return value.toLocaleString();
    return Number(value.toFixed(4)).toString();
  }
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function ManualLinkDetailModal(
  props: ManualLinkDetailModalProps,
): React.ReactElement | null {
  const {
    isOpen,
    linkId,
    onClose,
    onUpdated,
    onDeactivated,
    apiBasePath,
    currentUser,
    onUserChange,
    adminPassword,
    onAdminPasswordChange,
    packageTypeOptions,
    linkReasonOptions,
    parseIdList = defaultParseIdList,
    dedupeTrades = defaultDedupeTrades,
    formatTimestamp = defaultFormatTimestamp,
    formatNotional = defaultFormatNotional,
    formatMetricValue = defaultFormatMetricValue,
  } = props;

  const [linkDetail, setLinkDetail] = useState<ManualLinkDetail | null>(null);
  const [trades, setTrades] = useState<ManualLinkTrade[]>([]);
  const [history, setHistory] = useState<ManualLinkHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [packageType, setPackageType] = useState('');
  const [linkReason, setLinkReason] = useState('');
  const [comment, setComment] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [addTradesInput, setAddTradesInput] = useState('');
  const [removeTradesInput, setRemoveTradesInput] = useState('');
  const [deactivateReason, setDeactivateReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [deactivating, setDeactivating] = useState(false);
  const [validation, setValidation] = useState<ManualLinkValidationItem[]>([]);

  const manualColor = useMemo(() => manualLinkColor(linkId ?? ''), [linkId]);
  const hasWritePassword = adminPassword.trim().length > 0;

  const addTag = useCallback(() => {
    const next = tagInput.trim();
    if (!next) return;
    if (tags.includes(next)) {
      setTagInput('');
      return;
    }
    setTags((prev) => [...prev, next]);
    setTagInput('');
  }, [tagInput, tags]);

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((item) => item !== tag));
  }, []);

  const fetchLinkDetails = useCallback(async () => {
    if (!linkId) return;
    setLoading(true);
    setError(null);
    setLinkDetail(null);
    setTrades([]);
    setHistory([]);
    setValidation([]);
    try {
      const res = await fetch(`${apiBasePath}/${encodeURIComponent(linkId)}`);
      const payload = await res.json();
      if (!res.ok) {
        setError(payload?.error || 'Failed to load manual link.');
        return;
      }
      setLinkDetail(payload.link as ManualLinkDetail);
      setTrades(dedupeTrades(payload.trades || []));
      setHistory(payload.history || []);
      if (Array.isArray(payload.validation)) {
        setValidation(payload.validation as ManualLinkValidationItem[]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load manual link.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [apiBasePath, dedupeTrades, linkId]);

  const handleSave = useCallback(async () => {
    if (!linkId) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {
        user: currentUser || undefined,
        admin_password: adminPassword || undefined,
        package_type: packageType || undefined,
        link_reason: linkReason || undefined,
        comment: comment || undefined,
        tags,
      };
      const addTrades = parseIdList(addTradesInput);
      const removeTrades = parseIdList(removeTradesInput);
      if (addTrades.length) payload.add_trades = addTrades;
      if (removeTrades.length) payload.remove_trades = removeTrades;

      const res = await fetch(`${apiBasePath}/${encodeURIComponent(linkId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const responsePayload = await res.json();
      if (!res.ok) {
        setError(responsePayload?.error || 'Failed to update manual link.');
        return;
      }
      setAddTradesInput('');
      setRemoveTradesInput('');
      await fetchLinkDetails();
      onUpdated?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to update manual link.';
      setError(msg);
    } finally {
      setSaving(false);
    }
  }, [
    addTradesInput,
    adminPassword,
    apiBasePath,
    comment,
    currentUser,
    fetchLinkDetails,
    linkId,
    linkReason,
    onUpdated,
    packageType,
    parseIdList,
    removeTradesInput,
    tags,
  ]);

  const handleDeactivate = useCallback(async () => {
    if (!linkId) return;
    setDeactivating(true);
    setError(null);
    try {
      const res = await fetch(`${apiBasePath}/${encodeURIComponent(linkId)}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user: currentUser || undefined,
          admin_password: adminPassword || undefined,
          reason: deactivateReason || undefined,
        }),
      });
      const responsePayload = await res.json();
      if (!res.ok) {
        setError(responsePayload?.error || 'Failed to deactivate link.');
        return;
      }
      onDeactivated?.(linkId);
      onUpdated?.();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to deactivate link.';
      setError(msg);
    } finally {
      setDeactivating(false);
    }
  }, [
    adminPassword,
    apiBasePath,
    currentUser,
    deactivateReason,
    linkId,
    onClose,
    onDeactivated,
    onUpdated,
  ]);

  useEffect(() => {
    if (!isOpen) return;
    fetchLinkDetails();
  }, [fetchLinkDetails, isOpen]);

  useEffect(() => {
    if (!linkDetail) return;
    setPackageType(linkDetail.package_type || '');
    setLinkReason(linkDetail.link_reason || '');
    setComment(linkDetail.user_comment || '');
    setTags(Array.isArray(linkDetail.tags) ? linkDetail.tags : []);
    setTagInput('');
  }, [linkDetail]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4"
      data-testid="manual-link-detail-modal"
    >
      <div className="w-full max-w-4xl overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: manualColor || '#64748b' }}
              data-testid="manual-link-detail-dot"
            />
            Manual Link Details
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
            aria-label="Close manual link details"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-300">
              <RefreshCw className="h-4 w-4 animate-spin" />
              Loading manual link...
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="text-[11px] uppercase tracking-wide text-slate-400">
                      Manual Package
                    </div>
                    <div className="text-sm font-semibold text-slate-100">
                      {linkDetail?.manual_package_id || '--'}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {linkDetail?.is_active ? 'Active' : 'Inactive'}
                    </div>
                  </div>
                  <div className="space-y-1 text-right">
                    <div className="text-[11px] uppercase tracking-wide text-slate-400">
                      Created
                    </div>
                    <div className="text-[11px] text-slate-200">
                      {linkDetail?.created_by || '--'}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {formatTimestamp(linkDetail?.created_at)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Edit Link
                    </div>
                    <div className="mt-3 space-y-3">
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          User
                        </span>
                        <input
                          value={currentUser}
                          onChange={(event) => onUserChange(event.target.value)}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          placeholder="username or email"
                          data-testid="manual-link-user-input"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Write Password
                        </span>
                        <input
                          type="password"
                          value={adminPassword}
                          onChange={(event) => onAdminPasswordChange(event.target.value)}
                          autoComplete="current-password"
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          placeholder="admin password"
                          data-testid="manual-link-admin-password"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Package Type
                        </span>
                        <select
                          value={packageType}
                          onChange={(event) => setPackageType(event.target.value)}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        >
                          {packageTypeOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Link Reason
                        </span>
                        <select
                          value={linkReason}
                          onChange={(event) => setLinkReason(event.target.value)}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        >
                          {linkReasonOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Tags
                        </span>
                        <div className="mt-1 flex gap-2">
                          <input
                            value={tagInput}
                            onChange={(event) => setTagInput(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') {
                                event.preventDefault();
                                addTag();
                              }
                            }}
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="comma or enter separated tags"
                          />
                          <button
                            type="button"
                            onClick={addTag}
                            className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500"
                          >
                            Add
                          </button>
                        </div>
                        {tags.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {tags.map((tag) => (
                              <span
                                key={tag}
                                className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200"
                              >
                                {tag}
                                <button
                                  type="button"
                                  onClick={() => removeTag(tag)}
                                  className="text-slate-400 hover:text-slate-200"
                                  aria-label={`Remove ${tag}`}
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Comment
                        </span>
                        <textarea
                          value={comment}
                          onChange={(event) => setComment(event.target.value)}
                          rows={3}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          placeholder="Add context for this manual link"
                        />
                      </label>
                      <div className="grid gap-2 md:grid-cols-2">
                        <label className="block">
                          <span className="text-[11px] uppercase tracking-wide text-slate-400">
                            Add Trades
                          </span>
                          <input
                            value={addTradesInput}
                            onChange={(event) => setAddTradesInput(event.target.value)}
                            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="trade or package ids"
                          />
                        </label>
                        <label className="block">
                          <span className="text-[11px] uppercase tracking-wide text-slate-400">
                            Remove Trades
                          </span>
                          <input
                            value={removeTradesInput}
                            onChange={(event) => setRemoveTradesInput(event.target.value)}
                            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="trade or package ids"
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        onClick={handleSave}
                        disabled={
                          saving || !currentUser || !hasWritePassword || !linkDetail
                        }
                        title={
                          !hasWritePassword
                            ? 'Enter the write password to update manual links'
                            : undefined
                        }
                        className="rounded border border-emerald-500/60 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
                        data-testid="manual-link-save-button"
                      >
                        {saving ? 'Saving...' : 'Save Changes'}
                      </button>
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Deactivate Link
                    </div>
                    <div className="mt-2 flex flex-col gap-2">
                      <input
                        value={deactivateReason}
                        onChange={(event) => setDeactivateReason(event.target.value)}
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        placeholder="Reason for deactivation"
                      />
                      <button
                        type="button"
                        onClick={handleDeactivate}
                        disabled={
                          deactivating || !currentUser || !hasWritePassword || !linkDetail
                        }
                        title={
                          !hasWritePassword
                            ? 'Enter the write password to deactivate manual links'
                            : undefined
                        }
                        className="rounded border border-rose-500/60 bg-rose-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                        data-testid="manual-link-deactivate-button"
                      >
                        {deactivating ? 'Deactivating...' : 'Deactivate Link'}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Linked Trades
                    </div>
                    <div className="mt-2 space-y-2">
                      {trades.length ? (
                        trades.map((trade) => (
                          <div
                            key={trade.trade_id}
                            className="rounded border border-slate-800/70 bg-slate-900/60 px-2 py-1"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono">{trade.trade_id}</span>
                              <span className="text-[10px] uppercase text-slate-400">
                                {trade.product_type || 'N/A'}
                              </span>
                            </div>
                            <div className="text-[11px] text-slate-300">
                              {trade.trade_label || '--'}
                            </div>
                            <div className="flex items-center justify-between text-[10px] text-slate-500">
                              <span>{trade.package_id}</span>
                              <span>{formatNotional(trade.notional ?? null)}</span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-slate-400">
                          No linked trades found.
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">Metrics</div>
                    <div className="mt-2">
                      <ManualLinkMetricsTable
                        metrics={linkDetail?.link_metrics ?? null}
                        formatValue={formatMetricValue}
                      />
                    </div>
                  </div>
                  {validation.length > 0 ? (
                    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                      <div className="uppercase tracking-wide text-slate-400">
                        Validation
                      </div>
                      <div className="mt-2">
                        <ManualLinkValidationList items={validation} />
                      </div>
                    </div>
                  ) : null}
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">History</div>
                    <div className="mt-2">
                      <ManualLinkHistoryTable
                        history={history}
                        formatTimestamp={(iso) => formatTimestamp(iso)}
                      />
                    </div>
                  </div>
                </div>
              </div>
              {error && (
                <div
                  className="rounded border border-rose-800/70 bg-rose-950/40 px-3 py-2 text-xs text-rose-200"
                  data-testid="manual-link-detail-error"
                >
                  {error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
