// ABOUTME: Tests for ManualLinkMetricsTable - the row-of-pairs metrics
// summary rendered inside the manual-link create / edit modal.
import { describe, expect, it } from '@jest/globals';
import { renderToStaticMarkup } from 'react-dom/server';
import * as React from 'react';
import { ManualLinkMetricsTable } from '../components/ManualLinkMetricsTable';

describe('ManualLinkMetricsTable', () => {
  it('renders empty-state copy when metrics is null/undefined', () => {
    const html = renderToStaticMarkup(<ManualLinkMetricsTable metrics={null} />);
    expect(html).toContain('No metrics');
  });

  it('renders empty-state copy when metrics is an empty record', () => {
    const html = renderToStaticMarkup(<ManualLinkMetricsTable metrics={{}} />);
    expect(html).toContain('No metrics');
  });

  it('renders one row per (key, value) entry', () => {
    const metrics = {
      total_notional: 1_000_000,
      total_premium: 1234.5,
      time_spread_seconds: 30,
    };
    const html = renderToStaticMarkup(
      <ManualLinkMetricsTable metrics={metrics} />,
    );
    expect(html).toContain('total notional');
    expect(html).toContain('total premium');
    expect(html).toContain('time spread seconds');
  });

  it('replaces underscores with spaces in displayed key labels', () => {
    const html = renderToStaticMarkup(
      <ManualLinkMetricsTable metrics={{ avg_fixed_rate: 0.04 }} />,
    );
    expect(html).toContain('avg fixed rate');
    expect(html).not.toContain('avg_fixed_rate');
  });

  it('formats numeric values via the default formatter', () => {
    const html = renderToStaticMarkup(
      <ManualLinkMetricsTable metrics={{ count: 42 }} />,
    );
    expect(html).toContain('42');
  });

  it('formats nullish values as --', () => {
    const html = renderToStaticMarkup(
      <ManualLinkMetricsTable metrics={{ missing: null }} />,
    );
    expect(html).toContain('--');
  });

  it('accepts a custom value formatter', () => {
    const html = renderToStaticMarkup(
      <ManualLinkMetricsTable
        metrics={{ x: 5 }}
        formatValue={(v) => `[${String(v)}]`}
      />,
    );
    expect(html).toContain('[5]');
  });
});
