// ABOUTME: Pin that all six manual-link endpoints (POST + GET on /links,
// GET + PATCH + DELETE on /links/[linkId], plus validate_only=true POST)
// are reachable from the v2 base path. The route handlers themselves
// re-export from the shared usd-swap -> sofr-swap chain, so we just
// verify the re-exports are intact and the named exports match.
import { describe, expect, it } from '@jest/globals';

import * as listRoute from '../route';
import * as detailRoute from '../[linkId]/route';

describe('manual-links route audit (v2 base path)', () => {
  describe('/api/usd-swaps-tape-v2/links', () => {
    it('exports a POST handler (used for create + validate)', () => {
      expect(typeof listRoute.POST).toBe('function');
    });

    it('exports a GET handler (used for list)', () => {
      expect(typeof listRoute.GET).toBe('function');
    });
  });

  describe('/api/usd-swaps-tape-v2/links/[linkId]', () => {
    it('exports a GET handler (used for detail)', () => {
      expect(typeof detailRoute.GET).toBe('function');
    });

    it('exports a PATCH handler (used for edit, admin-password gated)', () => {
      expect(typeof detailRoute.PATCH).toBe('function');
    });

    it('exports a DELETE handler (used for deactivate, admin-password gated)', () => {
      expect(typeof detailRoute.DELETE).toBe('function');
    });
  });

  describe('shared usd-swap chain', () => {
    it('list route matches the usd-swap re-export source', async () => {
      const usd = await import('../../../usd-swap/links/route');
      expect(listRoute.GET).toBe(usd.GET);
      expect(listRoute.POST).toBe(usd.POST);
    });

    it('detail route matches the usd-swap re-export source', async () => {
      const usd = await import('../../../usd-swap/links/[linkId]/route');
      expect(detailRoute.GET).toBe(usd.GET);
      expect(detailRoute.PATCH).toBe(usd.PATCH);
      expect(detailRoute.DELETE).toBe(usd.DELETE);
    });
  });
});
