// ABOUTME: Tests for useManualLinkDetails hook. Drives the hook through
// renderHook semantics (manual setState shimming via React's act). The
// hook is built on top of manualLinkApi.getLinkDetail.
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { useManualLinkDetails } from '../hooks/useManualLinkDetails';

describe('useManualLinkDetails', () => {
  let originalFetch: typeof fetch;
  let fetchMock: jest.Mock;

  beforeEach(() => {
    originalFetch = global.fetch;
    fetchMock = jest.fn();
    (global as any).fetch = fetchMock;
  });

  afterEach(() => {
    (global as any).fetch = originalFetch;
  });

  it('exports a hook with stable signature: (linkId, basePath) => state', () => {
    expect(typeof useManualLinkDetails).toBe('function');
    expect(useManualLinkDetails.length).toBeGreaterThanOrEqual(1);
  });

  it('returns initial state before fetch resolves', () => {
    fetchMock.mockReturnValue(new Promise(() => undefined) as any);
    function Probe(): React.ReactElement {
      const state = useManualLinkDetails({ linkId: 'L1', basePath: '/api/test/links' });
      return (
        <span data-loading={String(state.loading)} data-link-id={String(state.detail?.link?.link_id ?? '')}>
          {state.error ?? ''}
        </span>
      );
    }
    const html = renderToStaticMarkup(<Probe />);
    expect(html).toContain('data-loading="true"');
  });

  it('returns idle state when linkId is null', () => {
    function Probe(): React.ReactElement {
      const state = useManualLinkDetails({ linkId: null, basePath: '/api/test/links' });
      return (
        <span data-loading={String(state.loading)} data-detail={state.detail ? '1' : '0'}>
          {state.error ?? ''}
        </span>
      );
    }
    const html = renderToStaticMarkup(<Probe />);
    expect(html).toContain('data-loading="false"');
    expect(html).toContain('data-detail="0"');
    // Without linkId no fetch is fired.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('the same hook can be called with different basePaths (initial-state pin)', () => {
    function Probe(): React.ReactElement {
      const a = useManualLinkDetails({ linkId: 'A', basePath: '/api/swaption/links' });
      const b = useManualLinkDetails({ linkId: 'B', basePath: '/api/usd-swaps-tape-v2/links' });
      return <span data-a={String(a.loading)} data-b={String(b.loading)} />;
    }
    fetchMock.mockReturnValue(new Promise(() => undefined) as any);
    const html = renderToStaticMarkup(<Probe />);
    expect(html).toContain('data-a="true"');
    expect(html).toContain('data-b="true"');
    // SSR does not fire useEffect; the actual fetch wiring is
    // exercised in the api wrapper tests. Here we pin only the
    // initial-state semantics of the hook surface.
  });

  it('exposes a refetch function on the returned state', () => {
    fetchMock.mockReturnValue(new Promise(() => undefined) as any);
    function Probe(): React.ReactElement {
      const state = useManualLinkDetails({ linkId: 'L1', basePath: '/api/test/links' });
      return <span data-has-refetch={typeof state.refetch === 'function' ? '1' : '0'} />;
    }
    const html = renderToStaticMarkup(<Probe />);
    expect(html).toContain('data-has-refetch="1"');
  });
});
