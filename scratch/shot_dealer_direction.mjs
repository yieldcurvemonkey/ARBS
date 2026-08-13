// ABOUTME: Screenshots every new view, headless, against a running dev server.
//
// The Chrome MCP is unusable in this session (chrome-devtools disconnected;
// claude-in-chrome needs a human to pick between two connected browsers), and
// "it typechecks" is not evidence that a chart renders. Puppeteer is already a
// dependency of this package and already drives the e2e suite, so it does the
// same job with no MCP in the path.
//
//   node scratch/shot_dealer_direction.mjs [baseUrl] [outDir]
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

// puppeteer lives in the dashboard package, not here. createRequire resolves it
// from that package root whatever the cwd is — an ESM import of an absolute
// Windows path is rejected as a bad URL scheme ('c:').
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3000'
const OUT = process.argv[3] ?? 'C:/Users/chris/clee/ARBS-fe/docs/dealer_direction/img'
fs.mkdirSync(OUT, { recursive: true })

const shots = []
const fail = []

async function shoot(page, sel, name, note) {
  const el = await page.$(sel)
  if (!el) {
    fail.push(`${name}: selector ${sel} not found`)
    return false
  }
  const file = path.join(OUT, `${name}.png`)
  await el.screenshot({ path: file })
  const { size } = fs.statSync(file)
  shots.push(`${name.padEnd(38)} ${String(size).padStart(8)} B  ${note}`)
  if (size < 3000) fail.push(`${name}: ${size} B — almost certainly blank`)
  return true
}

/** Click the tab whose label is exactly `label`. */
async function tab(page, label) {
  await page.evaluate((l) => {
    const b = [...document.querySelectorAll('button,a,div[role=tab]')].find(
      (x) => (x.textContent ?? '').trim() === l,
    )
    b?.click()
  }, label)
}

/** Set a <select> by visible option text and fire React's change event. */
async function pick(page, panelSel, optionText) {
  return page.evaluate(
    (ps, txt) => {
      const root = document.querySelector(ps)
      if (!root) return false
      for (const sel of root.querySelectorAll('select')) {
        const opt = [...sel.options].find((o) => o.textContent?.trim() === txt)
        if (!opt) continue
        const setter = Object.getOwnPropertyDescriptor(
          window.HTMLSelectElement.prototype, 'value')?.set
        setter?.call(sel, opt.value)
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        return true
      }
      return false
    },
    panelSel, optionText,
  )
}

/** Click a filter chip inside a panel by its exact label. */
async function clickChip(page, panelSel, label) {
  return page.evaluate(
    (ps, l) => {
      const root = document.querySelector(ps)
      const b = [...(root?.querySelectorAll('button') ?? [])].find(
        (x) => (x.textContent ?? '').trim() === l)
      if (!b) return false
      b.click()
      return true
    },
    panelSel, label,
  )
}

async function setDate(page, panelSel, iso) {
  return page.evaluate(
    (ps, v) => {
      const root = document.querySelector(ps)
      const inp = root?.querySelector('input[type=date]')
      if (!inp) return false
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value')?.set
      setter?.call(inp, v)
      inp.dispatchEvent(new Event('change', { bubbles: true }))
      return true
    },
    panelSel, iso,
  )
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * Wait until the heatmap has real columns.
 *
 * A FIXED SLEEP IS WHAT CAUSED THE BUG THIS SCRIPT EXISTS TO CATCH. /standardised
 * returns 6,290 rows; at 2.5s the panel was still in flight and rendered ten
 * labelled bucket rows with empty strips, which is indistinguishable from "no
 * data". Screenshotting that would have banked a picture of a defect as
 * evidence the feature works.
 */
async function waitForHeatmap(page, timeout = 120_000) {
  await page.waitForFunction(
    () => {
      const rows = [...document.querySelectorAll('[data-testid^="dd-z-row-"]')]
      if (rows.length === 0) return false
      const strip = rows[0].querySelector('span.flex.min-w-0.flex-1')
      // at least 10 painted cells, and no loading placeholder anywhere
      return (
        !document.querySelector('[data-testid="dd-z-strip-loading"]') &&
        (strip?.children.length ?? 0) >= 10
      )
    },
    { timeout, polling: 250 },
  )
}

/** Wait until the prints panel has drawn marks (or has honestly said it cannot). */
async function waitForPrints(page, timeout = 120_000) {
  await page.waitForFunction(
    () => {
      const p = document.querySelector('[data-testid="intraday-prints-panel"]')
      if (!p) return false
      const t = p.textContent ?? ''
      if (/loading/i.test(t)) return false
      return p.querySelectorAll('svg path, svg circle').length > 5 || /no prints/i.test(t)
    },
    { timeout, polling: 250 },
  )
}

const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
})
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100, deviceScaleFactor: 2 })
  page.on('pageerror', (e) => fail.push(`pageerror: ${e.message}`))
  page.on('console', (m) => {
    if (m.type() === 'error') fail.push(`console.error: ${m.text().slice(0, 200)}`)
  })

  // waitUntil:'domcontentloaded', NEVER networkidle0 — the tape polls every 30s
  // so the network is never idle and networkidle0 always times out.
  await page.goto(`${BASE}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="trade-tape-table"]', { timeout: 120_000 })
  await page.waitForSelector('[data-testid^="dd-direction-"]', { timeout: 120_000 })

  // THE ONBOARDING MODAL SITS ON TOP OF EVERY PANEL ("How to use the USD swaps
  // tape"). Screenshot it and you photograph the tour, not the feature.
  await sleep(1200)
  await page.evaluate(() => {
    const hit = [...document.querySelectorAll('button')].find((b) =>
      /^(skip|close|got it|dismiss)$/i.test((b.textContent ?? '').trim()) ||
      b.getAttribute('aria-label')?.toLowerCase().includes('close'))
    hit?.click()
  })
  await sleep(700)
  const modalGone = await page.evaluate(
    () => !/how to use the usd swaps tape/i.test(document.body.textContent ?? ''))
  if (!modalGone) fail.push('onboarding modal still covering the page')
  await sleep(800)

  // 1 — the direction column on the tape grid
  await shoot(page, '[data-testid="trade-tape-table"]', 'fe-01-tape-direction-column',
    'dealer_direction on every row')

  // 2 — the ladder panel, z now populated (34,176 of 37,740 cells carry z_raw)
  await tab(page, 'Analytics')
  await page.waitForSelector('[data-testid="dd-z-heatmap"]', { timeout: 120_000 })
  await waitForHeatmap(page)
  await sleep(800)
  await shoot(page, '[data-testid="dd-z-heatmap"]', 'fe-02-ladder-z-heatmap',
    'cross-bucket z — the ONLY thing that may cross buckets')

  // 3 — the exclusion breakdown, one click from the coverage figure
  const tgl = await page.$('[data-testid="dd-coverage-toggle"]')
  if (tgl) {
    // .click() from the page, not the handle: the handle click hit-tests and
    // silently lands on whatever overlaps.
    await page.evaluate(() => document.querySelector('[data-testid="dd-coverage-toggle"]')?.click())
    await page.waitForSelector('[data-testid="dd-exclusion-breakdown"]', { timeout: 60_000 })
    await sleep(900)
    await shoot(page, '[data-testid="dd-exclusion-breakdown"]', 'fe-03-exclusion-breakdown',
      'every excluded unit, one reason code each')
    await page.evaluate(() => document.querySelector('[data-testid="dd-coverage-toggle"]')?.click())
    await sleep(300)
  } else {
    fail.push('dd-coverage-toggle not found')
  }

  // 4 — the intraday prints panel, grid line, default day
  const P = '[data-testid="intraday-prints-panel"]'
  await page.waitForSelector(P, { timeout: 120_000 })
  await page.evaluate((s) => document.querySelector(s)?.scrollIntoView(), P)
  await waitForPrints(page)
  await sleep(1200)
  await shoot(page, P, 'fe-04-intraday-prints-grid',
    'SOFR 10Y D2C — modelled 1-min par grid + rec/paid marks')

  // 5 — 2025-04-09, the busiest measured SOFR 10Y D2C day (332 prints)
  if (await setDate(page, P, '2025-04-09')) {
    await sleep(1200)
    await waitForPrints(page)
    await sleep(1200)
    await shoot(page, P, 'fe-05-intraday-prints-busy-day',
      '2025-04-09, 332 prints — the line under a full day of flow')
  } else {
    fail.push('could not set the date input')
  }

  // 6 — Fed Funds. Same panel, a different curve: USD-FEDFUNDS-1D, never SOFR.
  if (await clickChip(page, P, 'FED_FUNDS')) {
    await sleep(1200)
    await waitForPrints(page)
    await sleep(1200)
    await shoot(page, P, 'fe-06-intraday-prints-fedfunds',
      'FED_FUNDS — routed to USD-FEDFUNDS-1D, not the SOFR curve')

    // 6b — a Fed Funds tenor the grid does NOT carry. MEASURED: no FF day in
    // the whole tape has >=12 prints at 7Y/20Y/30Y, so this is the
    // missing-grid disclosure with an empty day behind it — a guard that does
    // not fire on today's data, photographed so it is on the record anyway.
    if (await clickChip(page, P, '30Y')) {
      await sleep(1200)
      await waitForPrints(page)
      await sleep(1000)
      await shoot(page, P, 'fe-06b-intraday-prints-ff-no-grid',
        'FED_FUNDS 30Y — the grid does not carry this tenor')
    }
  } else {
    fail.push('could not switch rateIndex to FED_FUNDS')
  }

  // 7 — the whole analytics view, both panels together
  await page.evaluate(() => window.scrollTo(0, 0))
  await sleep(1200)
  await page.screenshot({
    path: path.join(OUT, 'fe-07-analytics-view.png'),
    fullPage: true,
  })
  const { size } = fs.statSync(path.join(OUT, 'fe-07-analytics-view.png'))
  shots.push(`${'fe-07-analytics-view'.padEnd(38)} ${String(size).padStart(8)} B  full page`)
} finally {
  await browser.close()
}

console.log('\nwrote:')
for (const s of shots) console.log('  ' + s)
if (fail.length) {
  console.log(`\n${fail.length} PROBLEM(S):`)
  for (const f of [...new Set(fail)]) console.log('  - ' + f)
  process.exit(1)
}
console.log('\nno page errors, no console errors, nothing blank')
