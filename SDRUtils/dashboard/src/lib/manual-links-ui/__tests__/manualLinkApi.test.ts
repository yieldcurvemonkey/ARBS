// ABOUTME: Tests for the manualLinkApi typed wrapper. Stubs global fetch
// to assert the right URL / method / body shape for each operation.
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { createManualLinkApi } from '../api/manualLinkApi';

describe('manualLinkApi', () => {
  let originalFetch: typeof fetch;
  let fetchMock: jest.Mock<any>;

  beforeEach(() => {
    originalFetch = global.fetch;
    fetchMock = jest.fn() as jest.Mock<any>;
    (global as any).fetch = fetchMock;
  });

  afterEach(() => {
    (global as any).fetch = originalFetch;
  });

  function okJson(payload: unknown) {
    return { ok: true, status: 200, json: async () => payload };
  }
  function failJson(payload: unknown, status = 400) {
    return { ok: false, status, json: async () => payload };
  }

  it('createLink POSTs JSON to base path', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ link_id: 'L1', manual_package_id: 'P1' }) as any);
    const api = createManualLinkApi('/api/test/links');
    const result = await api.createLink({
      trade_ids: ['t1', 't2'],
      package_type: 'CUSTOM',
      created_by: 'tester',
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/test/links');
    expect(init.method).toBe('POST');
    expect((init.headers as any)['Content-Type']).toBe('application/json');
    const body = JSON.parse(init.body as string);
    expect(body.trade_ids).toEqual(['t1', 't2']);
    expect(body.validate_only).toBeUndefined();
    expect(result?.link_id).toBe('L1');
  });

  it('validateLink POSTs with validate_only=true', async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ validation: [], metrics: { trade_count: 2 } }) as any,
    );
    const api = createManualLinkApi('/api/test/links');
    const out = await api.validateLink({
      trade_ids: ['t1', 't2'],
      created_by: 'tester',
    });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body.validate_only).toBe(true);
    expect(out.metrics?.trade_count).toBe(2);
  });

  it('getLinkDetail GETs /links/:id', async () => {
    fetchMock.mockResolvedValueOnce(
      okJson({ link: { link_id: 'L1' }, trades: [], history: [] }) as any,
    );
    const api = createManualLinkApi('/api/test/links');
    const detail = await api.getLinkDetail('L1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/test/links/L1');
    expect(detail.link.link_id).toBe('L1');
  });

  it('getLinkDetail percent-encodes the link id', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ link: {}, trades: [], history: [] }) as any);
    const api = createManualLinkApi('/api/test/links');
    await api.getLinkDetail('id with spaces');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/test/links/id%20with%20spaces');
  });

  it('updateLink PATCHes with admin_password in the JSON body', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ link_id: 'L1' }) as any);
    const api = createManualLinkApi('/api/test/links');
    await api.updateLink('L1', { user_comment: 'note', tags: ['a'] }, 'pw');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/test/links/L1');
    expect(init.method).toBe('PATCH');
    const body = JSON.parse(init.body as string);
    expect(body.admin_password).toBe('pw');
    expect(body.user_comment).toBe('note');
    expect(body.tags).toEqual(['a']);
  });

  it('deactivateLink DELETEs with admin_password in the JSON body', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ ok: true }) as any);
    const api = createManualLinkApi('/api/test/links');
    await api.deactivateLink('L1', 'pw', 'user-error');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/test/links/L1');
    expect(init.method).toBe('DELETE');
    const body = JSON.parse(init.body as string);
    expect(body.admin_password).toBe('pw');
    expect(body.reason).toBe('user-error');
  });

  it('throws on non-2xx with the server-supplied error message', async () => {
    fetchMock.mockResolvedValueOnce(failJson({ error: 'nope' }) as any);
    const api = createManualLinkApi('/api/test/links');
    await expect(
      api.createLink({ trade_ids: [], created_by: 'x' }),
    ).rejects.toThrow(/nope/);
  });

  it('throws a generic message when server payload omits error field', async () => {
    fetchMock.mockResolvedValueOnce(failJson({}, 500) as any);
    const api = createManualLinkApi('/api/test/links');
    await expect(api.getLinkDetail('L1')).rejects.toThrow(/500|failed|error/i);
  });

  it('listLinks GETs /links with optional querystring params', async () => {
    fetchMock.mockResolvedValueOnce(okJson({ items: [] }) as any);
    const api = createManualLinkApi('/api/test/links');
    await api.listLinks({ limit: 10, is_active: true });
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toMatch(/limit=10/);
    expect(url).toMatch(/is_active=true/);
  });
});
