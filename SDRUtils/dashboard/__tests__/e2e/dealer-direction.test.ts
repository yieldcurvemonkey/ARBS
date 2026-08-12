/**
 * Puppeteer E2E for the dealer-direction column and the risk-bucket ladder.
 *
 * Gated on E2E_BASE_URL like the sibling suite. Run:
 *   E2E_BASE_URL=http://localhost:3021 npm run test:e2e
 *
 * These assert the two things a unit test cannot: that the direction cell
 * actually reaches the DOM through the real route, and that the panel's
 * refusal survives the whole stack rather than only the module that declares
 * it.
 */
import { describe, expect, it } from '@jest/globals'
import puppeteer from 'puppeteer'

const BASE_URL = process.env.E2E_BASE_URL
const describeIfUrl = BASE_URL ? describe : describe.skip

describeIfUrl('dealer direction — end to end', () => {
  const url = BASE_URL ?? ''

  it('renders a direction cell on every tape row', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
      await page.waitForSelector('[data-testid="trade-tape-table"]', {
        timeout: 30_000,
      })
      await page.waitForSelector('[data-testid^="dd-direction-"]', {
        timeout: 30_000,
      })
      const cells = await page.$$eval(
        '[data-testid^="dd-direction-"]',
        (els) => els.map((e) => ({
          text: (e.textContent ?? '').trim(),
          dir: e.getAttribute('data-direction'),
        })),
      )
      expect(cells.length).toBeGreaterThan(0)
      // Three states and only three: a call, a declined call, or a day the
      // batch has not reached. Never a bare blank.
      for (const c of cells) {
        expect(['RCVD', 'PAID', 'n/a', '—']).toContain(c.text)
        expect(['RECEIVED', 'PAID', 'ABSTAINED', 'UNKNOWN']).toContain(c.dir)
      }
    } finally {
      await browser.close()
    }
  }, 120_000)

  it('the ladder panel renders its z grid and its bucket detail', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
      await page.waitForSelector('[data-testid="trade-tape-table"]', {
        timeout: 30_000,
      })
      // The Analytics view is where the panel is mounted.
      await page.evaluate(() => {
        const b = [...document.querySelectorAll('button,a,div[role=tab]')]
          .find((x) => (x.textContent ?? '').trim() === 'Analytics')
        ;(b as HTMLElement | undefined)?.click()
      })
      await page.waitForSelector('[data-testid="dd-z-heatmap"]', {
        timeout: 30_000,
      })
      const rows = await page.$$('[data-testid^="dd-z-row-"]')
      expect(rows.length).toBe(10)

      // Coverage is not a footnote: it is on screen and it is the click
      // target for the breakdown.
      const toggle = await page.$('[data-testid="dd-coverage-toggle"]')
      expect(toggle).not.toBeNull()
      await toggle!.click()
      await page.waitForSelector('[data-testid="dd-exclusion-breakdown"]', {
        timeout: 15_000,
      })
    } finally {
      await browser.close()
    }
  }, 120_000)

  it('the level endpoint refuses a bucket list over HTTP', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      // Navigate first: a fetch from about:blank has a null origin and fails
      // CORS before it reaches the route, which looks exactly like the route
      // being broken.
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
      const res = await page.evaluate(async (base: string) => {
        const r = await fetch(
          `${base}/api/usd-swaps-tape-v2/direction/bucket?bucket=5-7Y&bucket=7-10Y`)
        return { status: r.status, body: await r.json() }
      }, url)
      expect(res.status).toBe(400)
      expect(String(res.body.error)).toMatch(/0\.761/)
    } finally {
      await browser.close()
    }
  }, 60_000)

  it('the all-bucket endpoint returns no level key over HTTP', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
      const keys = await page.evaluate(async (base: string) => {
        const r = await fetch(
          `${base}/api/usd-swaps-tape-v2/direction/standardised?venueClass=D2C&series=FLOW`)
        const j = await r.json()
        const out = new Set<string>()
        for (const row of j.rows ?? []) for (const k of Object.keys(row)) out.add(k)
        return [...out]
      }, url)
      // The property that must hold whatever the window contains.
      for (const k of keys) {
        expect(k).not.toMatch(/^(delta_dv01|abs_dv01)/)
      }
      // An empty ladder trivially satisfies "no level key", so say out loud
      // which of the two situations this run was in rather than banking a
      // vacuous pass.
      if (keys.length === 0) {
        // eslint-disable-next-line no-console
        console.warn(
          'the ladder table is empty for this window — the no-level ' +
            'assertion above was VACUOUS. Run `publish` before trusting it.',
        )
      } else {
        expect(keys).toContain('z_raw')
        expect(keys).toContain('coverage_frac')
      }
    } finally {
      await browser.close()
    }
  }, 60_000)
})
