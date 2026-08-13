// ABOUTME: Why is the z heatmap blank when z_raw is populated?
//
// The table has z for every one of the last 490 cells (z_n_obs 250). The API
// serves 6,290 rows back to 2024-07-01, whose EARLIEST rows legitimately carry
// null z because the rolling window has not accumulated yet. So "blank" is
// either the panel rendering the wrong end of the window, or rendering all 629
// dates into a fixed width at ~2.5px a column.
//
// This asks the DOM rather than guessing.
import { createRequire } from 'node:module'
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3000'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100 })
  await page.goto(`${BASE}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="trade-tape-table"]', { timeout: 120_000 })
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button,a,div[role=tab]')]
      .find((x) => (x.textContent ?? '').trim() === 'Analytics')
    b?.click()
  })
  await page.waitForSelector('[data-testid="dd-z-heatmap"]', { timeout: 120_000 })
  await sleep(3000)

  const out = await page.evaluate(() => {
    const hm = document.querySelector('[data-testid="dd-z-heatmap"]')
    const rows = [...document.querySelectorAll('[data-testid^="dd-z-row-"]')]
    const r0 = rows[0]
    const kids = r0 ? [...r0.children] : []
    const cellInfo = kids.slice(0, 6).map((k) => ({
      tag: k.tagName,
      cls: (k.className || '').toString().slice(0, 60),
      w: Math.round(k.getBoundingClientRect().width),
      bg: getComputedStyle(k).backgroundColor,
      txt: (k.textContent ?? '').trim().slice(0, 12),
      testid: k.getAttribute('data-testid'),
    }))
    // any descendant carrying a non-transparent, non-slate background?
    const painted = r0
      ? [...r0.querySelectorAll('*')].filter((e) => {
          const b = getComputedStyle(e).backgroundColor
          return b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent'
        }).length
      : 0
    return {
      heatmapBox: hm ? hm.getBoundingClientRect().toJSON() : null,
      nRows: rows.length,
      row0TestId: r0?.getAttribute('data-testid'),
      row0ChildCount: kids.length,
      row0Text: (r0?.textContent ?? '').trim().slice(0, 160),
      cellInfo,
      paintedDescendants: painted,
      heatmapText: (hm?.textContent ?? '').trim().slice(0, 400),
    }
  })
  console.log(JSON.stringify(out, null, 2))

  // and what did the panel actually FETCH?
  const reqs = []
  page.on('response', (r) => {
    if (r.url().includes('/direction/')) reqs.push(`${r.status()} ${r.url().replace(BASE, '')}`)
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button,a,div[role=tab]')]
      .find((x) => (x.textContent ?? '').trim() === 'Analytics')
    b?.click()
  })
  await sleep(6000)
  console.log('\ndirection requests:')
  for (const r of [...new Set(reqs)]) console.log('  ' + r)
} finally {
  await browser.close()
}
