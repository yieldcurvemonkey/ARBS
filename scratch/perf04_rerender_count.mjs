// ABOUTME: Is the prints chart SLOW, or is it slow SEVERAL TIMES?
//
// 2,494 ms of JS for 313 marks is ~8 ms a mark, which is far too much to be
// element creation -- and the profile agrees: React.createElement is only 382
// ms of it, while ~1,476 ms sits inside recharts itself. Animation is already
// off and the custom shape emits exactly one <path>. So the suspicion is that
// the chart renders the heavy dataset more than once per interaction:
//
//   setLoading(true)  -> render with the OLD 313 marks   (wasted)
//   setData(body)     -> render with the NEW marks       (the only one wanted)
//   setLoading(false) -> render again                    (wasted)
//
// If that is what is happening the fix is memoisation, not a rewrite of the
// mark renderer. This counts the chart's actual re-renders by watching the
// recharts <Surface> get rebuilt, and breaks the DOM down by class so the
// 2,680 layers are attributed rather than guessed at.
import { createRequire } from 'node:module'
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3100'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100 })
  await page.goto(`${BASE}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('[data-testid="trade-tape-table"]', { timeout: 180_000 })
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
  await page.waitForFunction(
    () => {
      const p = document.querySelector('[data-testid="intraday-prints-panel"]')
      return p && !/loading prints/i.test(p.textContent ?? '')
        && p.querySelectorAll('svg path, svg circle').length > 5
    }, { timeout: 180_000, polling: 100 })
  await sleep(2500)

  // --- who owns the 2,680 layers? -----------------------------------------
  const hist = await page.evaluate(() => {
    const p = document.querySelector('[data-testid="intraday-prints-panel"]')
    const h = {}
    for (const el of p.querySelectorAll('*')) {
      const c = (el.getAttribute('class') || '').split(/\s+/).filter((x) => x.startsWith('recharts-'))
      for (const k of c) h[k] = (h[k] ?? 0) + 1
    }
    return Object.entries(h).sort((a, b) => b[1] - a[1]).slice(0, 12)
  })
  console.log('\nDOM BY RECHARTS CLASS (default day)')
  for (const [k, n] of hist) console.log(`  ${String(n).padStart(6)}  ${k}`)

  // --- count chart rebuilds across a date change --------------------------
  await page.evaluate(() => {
    window.__r = { surfaceMut: 0, batches: 0, at: [] }
    const w = document.querySelector('[data-testid="intraday-prints-panel"] .recharts-wrapper')
    if (!w) return
    new MutationObserver((ms) => {
      window.__r.batches += 1
      window.__r.surfaceMut += ms.length
      window.__r.at.push(Math.round(performance.now()))
    }).observe(w, { childList: true, subtree: true })
  })

  const t0 = Date.now()
  await page.evaluate(() => {
    const root = document.querySelector('[data-testid="intraday-prints-panel"]')
    const inp = root?.querySelector('input[type=date]')
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
    set?.call(inp, '2025-04-09')
    inp?.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForFunction(
    () => (document.querySelector('[data-testid="intraday-prints-panel"]')
      ?.querySelectorAll('svg path, svg circle').length ?? 0) > 300,
    { timeout: 300_000, polling: 50 })
  const wall = Date.now() - t0
  await sleep(1500)

  const r = await page.evaluate(() => {
    const a = window.__r.at
    const t0 = a[0] ?? 0
    // cluster mutation batches into "renders": a gap > 120ms starts a new one
    const clusters = []
    let cur = null
    for (const t of a) {
      if (cur == null || t - cur.end > 120) { cur = { start: t, end: t, n: 1 }; clusters.push(cur) }
      else { cur.end = t; cur.n += 1 }
    }
    return {
      batches: window.__r.batches, mutations: window.__r.surfaceMut,
      clusters: clusters.map((c) => ({ atMs: Math.round(c.start - t0), spanMs: c.end - c.start, batches: c.n })),
    }
  })
  console.log(`\nDATE CHANGE -> 2025-04-09   wall ${wall} ms`)
  console.log(`  DOM mutation batches inside the chart: ${r.batches} (${r.mutations} mutations)`)
  console.log('  clustered into distinct chart rebuilds (>120ms apart):')
  for (const c of r.clusters) {
    console.log(`    +${String(c.atMs).padStart(6)} ms   span ${String(c.spanMs).padStart(5)} ms   ${c.batches} batches`)
  }
  console.log(`  => ${r.clusters.length} rebuild(s) of a chart that only needed 1`)

  const hist2 = await page.evaluate(() => {
    const p = document.querySelector('[data-testid="intraday-prints-panel"]')
    const h = {}
    for (const el of p.querySelectorAll('*')) {
      const c = (el.getAttribute('class') || '').split(/\s+/).filter((x) => x.startsWith('recharts-'))
      for (const k of c) h[k] = (h[k] ?? 0) + 1
    }
    return Object.entries(h).sort((a, b) => b[1] - a[1]).slice(0, 8)
  })
  console.log('\nDOM BY RECHARTS CLASS (busiest day)')
  for (const [k, n] of hist2) console.log(`  ${String(n).padStart(6)}  ${k}`)
} finally {
  await browser.close()
}
