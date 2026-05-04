// ABOUTME: Type-level smoke tests pinning the consolidated manual-link
// types. These compile-time checks (via runtime no-op assertions) make
// sure both swaptions and usd-swaps-tape-v2 callers see compatible
// shapes. If a consumer's view of these shapes drifts apart this file
// breaks loudly at the lib level.
import { describe, expect, it } from '@jest/globals';
import type {
  ManualLinkDetail,
  ManualLinkDetailBundle,
  ManualLinkHistoryItem,
  ManualLinkTrade,
  ManualLinkValidationItem,
  ManualLinkValidationStatus,
  TapeRowLike,
} from '../types';

describe('manual-links-ui shared types', () => {
  it('ManualLinkValidationStatus enumerates ok/warn/error', () => {
    const vals: ManualLinkValidationStatus[] = ['ok', 'warn', 'error'];
    expect(vals).toHaveLength(3);
  });

  it('ManualLinkValidationItem accepts the canonical wire shape', () => {
    const item: ManualLinkValidationItem = {
      key: 'trade_count',
      label: 'Trade count',
      status: 'ok',
      message: '2 trades',
    };
    expect(item.status).toBe('ok');
  });

  it('ManualLinkTrade accepts a minimal record', () => {
    const trade: ManualLinkTrade = { trade_id: 't1', package_id: 'p1' };
    expect(trade.trade_id).toBe('t1');
  });

  it('ManualLinkHistoryItem accepts the canonical wire shape', () => {
    const item: ManualLinkHistoryItem = {
      history_id: 1,
      action: 'CREATE',
      changed_by: 'tester',
      changed_at: '2026-01-01T00:00:00Z',
      change_details: { foo: 1 },
      previous_state: null,
    };
    expect(item.history_id).toBe(1);
  });

  it('ManualLinkDetail accepts a complete record', () => {
    const link: ManualLinkDetail = {
      link_id: 'L1',
      manual_package_id: 'P1',
      package_type: 'CUSTOM',
      linked_trade_ids: ['t1', 't2'],
      created_by: 'tester',
      created_at: '2026-01-01T00:00:00Z',
      user_comment: 'note',
      link_reason: null,
      tags: ['a', 'b'],
      link_metrics: {},
      is_active: true,
    };
    expect(link.is_active).toBe(true);
  });

  it('ManualLinkDetailBundle composes link + trades + history', () => {
    const bundle: ManualLinkDetailBundle = {
      link: {
        link_id: 'L1',
        manual_package_id: 'P1',
        package_type: null,
        linked_trade_ids: [],
        created_by: '',
        created_at: '',
        is_active: true,
      },
      trades: [],
      history: [],
    };
    expect(bundle.trades).toEqual([]);
  });

  it('TapeRowLike is a structural intersection acceptable to consumer rows', () => {
    type SwaptionsRow = {
      manual_link_id?: string | null;
      manual_package_id?: string | null;
      package_source?: string | null;
      // ...lots of other unrelated fields...
      vol_grid_quadrant?: string;
    };
    const a: SwaptionsRow = { manual_link_id: 'x' };
    const lite: TapeRowLike = a;
    expect(lite.manual_link_id).toBe('x');
  });
});
