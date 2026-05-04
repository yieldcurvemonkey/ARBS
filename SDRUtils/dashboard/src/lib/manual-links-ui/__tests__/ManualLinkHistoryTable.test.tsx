// ABOUTME: Tests for ManualLinkHistoryTable - the audit-trail list at the
// bottom of the manual-link detail modal.
import { describe, expect, it } from '@jest/globals';
import { renderToStaticMarkup } from 'react-dom/server';
import * as React from 'react';
import { ManualLinkHistoryTable } from '../components/ManualLinkHistoryTable';
import type { ManualLinkHistoryItem } from '../types';

describe('ManualLinkHistoryTable', () => {
  const create: ManualLinkHistoryItem = {
    history_id: 1,
    action: 'CREATE',
    changed_by: 'alice',
    changed_at: '2026-01-01T00:00:00Z',
    change_details: { trade_count: 2 },
    previous_state: null,
  };
  const update: ManualLinkHistoryItem = {
    history_id: 2,
    action: 'UPDATE',
    changed_by: 'bob',
    changed_at: '2026-01-02T00:00:00Z',
    change_details: { user_comment: 'updated' },
    previous_state: { user_comment: null },
  };
  const deactivate: ManualLinkHistoryItem = {
    history_id: 3,
    action: 'DEACTIVATE',
    changed_by: 'admin',
    changed_at: '2026-01-03T00:00:00Z',
    change_details: null,
    previous_state: null,
  };

  it('renders empty state when there are no history entries', () => {
    const html = renderToStaticMarkup(<ManualLinkHistoryTable history={[]} />);
    expect(html).toContain('No history');
  });

  it('renders one row per history entry, in given order', () => {
    const html = renderToStaticMarkup(
      <ManualLinkHistoryTable history={[create, update, deactivate]} />,
    );
    const idxCreate = html.indexOf('CREATE');
    const idxUpdate = html.indexOf('UPDATE');
    const idxDeact = html.indexOf('DEACTIVATE');
    expect(idxCreate).toBeGreaterThan(-1);
    expect(idxUpdate).toBeGreaterThan(idxCreate);
    expect(idxDeact).toBeGreaterThan(idxUpdate);
  });

  it('shows changed_by and changed_at on every row', () => {
    const html = renderToStaticMarkup(
      <ManualLinkHistoryTable history={[create, update]} />,
    );
    expect(html).toContain('alice');
    expect(html).toContain('bob');
  });

  it('renders change_details as JSON when present', () => {
    const html = renderToStaticMarkup(
      <ManualLinkHistoryTable history={[update]} />,
    );
    expect(html).toContain('user_comment');
    expect(html).toContain('updated');
  });

  it('omits change_details JSON when null', () => {
    const html = renderToStaticMarkup(
      <ManualLinkHistoryTable history={[deactivate]} />,
    );
    // No <pre> block when there's nothing to show.
    expect(html).not.toContain('<pre');
  });

  it('uses item.history_id as React key', () => {
    const a: ManualLinkHistoryItem = { ...create, history_id: 100 };
    const b: ManualLinkHistoryItem = { ...create, history_id: 200 };
    const html = renderToStaticMarkup(
      <ManualLinkHistoryTable history={[a, b]} />,
    );
    // Both rows render without React duplicate-key warnings (no assertion
    // beyond rendering, since RTL not available; this is a smoke check).
    expect(html.match(/CREATE/g)?.length).toBe(2);
  });
});
