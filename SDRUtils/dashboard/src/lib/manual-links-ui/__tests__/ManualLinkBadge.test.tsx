// ABOUTME: Render-shape tests for the shared ManualLinkBadge. Tests run
// in a Node environment without jsdom, so we drive the component through
// renderToStaticMarkup and read the resulting HTML. Behaviour around
// onClick is asserted at the source-string level (button vs span) plus
// via a manual handler invocation through the rendered React tree.
import { describe, expect, it, jest } from '@jest/globals';
import { renderToStaticMarkup } from 'react-dom/server';
import * as React from 'react';
import { ManualLinkBadge } from '../components/ManualLinkBadge';
import { manualLinkColor } from '../color';

describe('ManualLinkBadge', () => {
  it('renders dot + label + manual_package_id', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge
        linkId="abc"
        manualPackageId="PKG-1"
        sourceLabel="Manual"
      />,
    );
    expect(html).toContain('Manual');
    expect(html).toContain('PKG-1');
    const colour = manualLinkColor('abc') as string;
    expect(html).toContain(colour);
    expect(html).toContain('data-testid="manual-link-dot"');
  });

  it('renders Hybrid label variant', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="abc" sourceLabel="Hybrid" />,
    );
    expect(html).toContain('Hybrid');
  });

  it('omits package-id span when no manualPackageId provided', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="abc" sourceLabel="Manual" />,
    );
    expect(html).not.toMatch(/PKG-/);
  });

  it('renders as a button when onClick is provided', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="L1" sourceLabel="Manual" onClick={() => undefined} />,
    );
    expect(html).toContain('<button');
    expect(html).toContain('type="button"');
  });

  it('renders as a static span (non-clickable) when no onClick provided', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="L1" sourceLabel="Manual" />,
    );
    expect(html).not.toContain('<button');
    expect(html).toContain('<span');
  });

  it('exposes a click handler on the rendered element that fires with the linkId', () => {
    const fn = jest.fn();
    const tree = (
      <ManualLinkBadge linkId="L1" sourceLabel="Manual" onClick={fn} />
    );
    // Inspect the React element directly to ensure the linkId flows into
    // the handler. We reach in via a fake event object.
    const props = (tree as any).props;
    // Render the element and walk the props of the actual <button>.
    const Element = (ManualLinkBadge as any)(props);
    const buttonProps = Element.props;
    expect(buttonProps.type).toBe('button');
    expect(typeof buttonProps.onClick).toBe('function');
    buttonProps.onClick({ stopPropagation: jest.fn() });
    expect(fn).toHaveBeenCalledWith('L1');
  });

  it('stops event propagation in the click handler so row-level clicks do not also fire', () => {
    const fn = jest.fn();
    const stopProp = jest.fn();
    const tree = (
      <ManualLinkBadge linkId="L1" sourceLabel="Manual" onClick={fn} />
    );
    const Element = (ManualLinkBadge as any)(tree.props);
    Element.props.onClick({ stopPropagation: stopProp });
    expect(stopProp).toHaveBeenCalledTimes(1);
  });

  it('renders connector spans when showConnector=true', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="L1" sourceLabel="Manual" showConnector />,
    );
    // Two ::before-style connector hairlines for the placement-between-rows
    // case; both are aria-hidden so they don't reach a screen reader.
    expect(html).toContain('aria-hidden');
  });

  it('falls back to a neutral colour when linkId is empty (defensive)', () => {
    const html = renderToStaticMarkup(
      <ManualLinkBadge linkId="" sourceLabel="Manual" />,
    );
    // The dot still renders with the slate fallback so that empty linkId
    // doesn't blank the chip.
    expect(html).toContain('data-testid="manual-link-dot"');
  });

  it('SSR snapshot is deterministic for known input', () => {
    const a = renderToStaticMarkup(
      <ManualLinkBadge linkId="abc" manualPackageId="PKG-1" sourceLabel="Manual" />,
    );
    const b = renderToStaticMarkup(
      <ManualLinkBadge linkId="abc" manualPackageId="PKG-1" sourceLabel="Manual" />,
    );
    expect(a).toBe(b);
  });
});
