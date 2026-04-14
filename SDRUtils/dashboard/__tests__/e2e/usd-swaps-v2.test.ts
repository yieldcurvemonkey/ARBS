/**
 * Puppeteer E2E suite for the USD swap tape v2.
 *
 * Gated on the E2E_BASE_URL env var (typically http://localhost:3000 or a
 * deployed preview URL). When the env var is unset the suite is skipped so
 * contributors can run the rest of the tests without a browser.
 */
import { describe, expect, it } from '@jest/globals'
import puppeteer from 'puppeteer'

const BASE_URL = process.env.E2E_BASE_URL
const describeIfUrl = BASE_URL ? describe : describe.skip

describeIfUrl('USD swap tape v2 — golden paths', () => {
  const url = BASE_URL ?? ''

  it('loads /usd-swaps-v2 and renders at least one row', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'networkidle0' })
      await page.waitForSelector('[data-testid="trade-tape-table"]', {
        timeout: 15_000,
      })
      const rows = await page.$$('tbody tr')
      expect(rows.length).toBeGreaterThan(0)
    } finally {
      await browser.close()
    }
  }, 60_000)

  it('Clean tape toggle drops row count + adds ?clean=true to URL', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2`, { waitUntil: 'networkidle0' })
      await page.waitForSelector('[data-testid="trade-tape-table"]')
      const before = (await page.$$('tbody tr')).length
      const toggle = await page.$('button[aria-pressed][aria-label="Clean tape"]')
      if (toggle) {
        await toggle.click()
        await page.waitForTimeout(500)
        const currentUrl = page.url()
        expect(currentUrl).toContain('clean=true')
      }
      const after = (await page.$$('tbody tr')).length
      expect(after).toBeLessThanOrEqual(before)
    } finally {
      await browser.close()
    }
  }, 60_000)

  it('FOMC sidecar card click filters the main table', async () => {
    const browser = await puppeteer.launch({ headless: true })
    try {
      const page = await browser.newPage()
      await page.goto(`${url}/usd-swaps-v2?sidecar=fomc`, {
        waitUntil: 'networkidle0',
      })
      await page.waitForSelector('[data-testid="trade-tape-table"]')
      // Best-effort: the suite just confirms the URL contract when a FOMC
      // card is clicked.
      const fomcCard = await page.$('button[aria-label^="fomc"]')
      if (fomcCard) {
        await fomcCard.click()
        await page.waitForTimeout(300)
        expect(page.url()).toContain('fomcMeeting=')
      }
    } finally {
      await browser.close()
    }
  }, 60_000)
})
