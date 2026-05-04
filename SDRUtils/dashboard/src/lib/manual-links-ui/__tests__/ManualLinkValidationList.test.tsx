// ABOUTME: Tests for ManualLinkValidationList - the validation-result list
// rendered inside the manual-link create / edit modal. Asserts every
// branch of severity rendering and the empty-state copy.
import { describe, expect, it } from '@jest/globals';
import { renderToStaticMarkup } from 'react-dom/server';
import * as React from 'react';
import { ManualLinkValidationList } from '../components/ManualLinkValidationList';
import type { ManualLinkValidationItem } from '../types';

describe('ManualLinkValidationList', () => {
  const okItem: ManualLinkValidationItem = {
    key: 'k1',
    label: 'OK item',
    status: 'ok',
    message: 'Looks good',
  };
  const warnItem: ManualLinkValidationItem = {
    key: 'k2',
    label: 'Warn item',
    status: 'warn',
    message: 'Caveat',
  };
  const errorItem: ManualLinkValidationItem = {
    key: 'k3',
    label: 'Err item',
    status: 'error',
    message: 'Will block',
  };

  it('renders the empty state copy when items list is empty', () => {
    const html = renderToStaticMarkup(
      <ManualLinkValidationList items={[]} />,
    );
    expect(html).toContain('Validation results will appear');
  });

  it('renders one row per item with label + message', () => {
    const html = renderToStaticMarkup(
      <ManualLinkValidationList items={[okItem, warnItem, errorItem]} />,
    );
    expect(html).toContain('OK item');
    expect(html).toContain('Looks good');
    expect(html).toContain('Warn item');
    expect(html).toContain('Caveat');
    expect(html).toContain('Err item');
    expect(html).toContain('Will block');
  });

  it('shows the appropriate icon styling per severity', () => {
    const html = renderToStaticMarkup(
      <ManualLinkValidationList items={[okItem, warnItem, errorItem]} />,
    );
    // The OK item uses emerald, warn uses amber, error uses rose.
    expect(html).toContain('text-emerald-400');
    expect(html).toContain('text-amber-300');
    expect(html).toContain('text-rose-400');
  });

  it('uses the item.key as the React key (no collisions)', () => {
    // Same labels but distinct keys must both render.
    const a: ManualLinkValidationItem = { ...okItem, key: 'a', label: 'X' };
    const b: ManualLinkValidationItem = { ...okItem, key: 'b', label: 'X' };
    const html = renderToStaticMarkup(
      <ManualLinkValidationList items={[a, b]} />,
    );
    const matches = html.match(/X<\/div>/g) ?? [];
    expect(matches.length).toBe(2);
  });
});
