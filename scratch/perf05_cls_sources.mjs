// ABOUTME: WHERE does the layout shift come from?
//
// Splitting the ladder's two fetches and shrinking the payload made the panels
// land at DIFFERENT times instead of together, and cumulative layout shift went
// 0.147 -> 0.258. That is a regression I introduced: each late-arriving strip
// pushes the chart below it down the page while the reader is already looking
// at it.
//
// layout-shift entries carry `sources` — the actual nodes that moved. This
// names them instead of guessing which strip it is.
import { createRequire } from 'node:module'
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3100'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100 })
  await page.evaluateOnNewDocument(() => {
    window.__shifts = []
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) {
        if (e.hadRecentInput) continue
        window.__shifts.push({
          value: e.value,
          t: Math.round(e.startTime),
          sources: (e.sources ?? []).slice(0, 3).map((s) => {
            const n = s.node
            if (!n) return '(detached)'
            const el = n.nodeType === 1 ? n : n.parentElement
            if (!el) return '(text)'
            const id = el.getAttribute?.('data-testid')
            const cls = (el.getAttribute?.('class') || '').split(/\s+/).slice(0, 3).join('.')
            return `${el.tagName}${id ? `[${id}]` : ''}${cls ? `.${cls}` : ''}`
              + `  ${Math.round(s.previousRect?.top ?? 0)}->${Math.round(s.currentRect?.top ?? 0)}`
          }),
        })
      }
    }).observe({ type: 'layout-shift', buffered: true })
  })

  await page.goto(`${BASE}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="trade-tape-table"]', { timeout: 120_000 })
  await sleep(1200)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      /^(skip|close|got it|dismiss)$/i.test((x.textContent ?? '').trim()))
    b?.click()
  })
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button,a,div[role=tab]')]
      .find((x) => (x.textContent ?? '').trim() === 'Analytics')
    b?.click()
  })
  await sleep(9000)

  const out = await page.evaluate(() => ({
    total: window.__shifts.reduce((s, x) => s + x.value, 0),
    worst: [...window.__shifts].sort((a, b) => b.value - a.value).slice(0, 10),
    n: window.__shifts.length,
  }))
  console.log(`\nCLS ${out.total.toFixed(3)} across ${out.n} shifts\n`)
  for (const s of out.worst) {
    console.log(`  ${s.value.toFixed(4)}  @${String(s.t).padStart(6)}ms`)
    for (const src of s.sources) console.log(`            ${src}`)
  }
} finally {
  await browser.close()
}
