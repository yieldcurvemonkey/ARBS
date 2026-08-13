// ABOUTME: What the browser pays for these panels — render weight, blocking
// time, memory, and whether the tape's 30s poll churns them.
//
// Server latency is only half the question on a data-intensive page. The
// ladder paints 600 heatmap cells, each with a title string built per render;
// the prints chart paints a ~1,150-point line plus a custom SVG path per mark
// and per deviation stem. None of that shows up in an endpoint timing.
//
// Measured against a PRODUCTION build. Dev-mode React double-invokes renders
// under StrictMode and skips every production optimisation, so dev numbers
// would overstate the render cost of the thing that actually ships.
//
//   node scratch/perf02_client.mjs [baseUrl]
import { createRequire } from 'node:module'
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3100'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const fmt = (n, d = 1) => (n == null ? '—' : Number(n).toFixed(d))

/** Long tasks (>50ms) block the main thread; their sum is the freeze the user feels. */
const OBSERVER = () => {
  window.__lt = []
  window.__ls = []
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__lt.push({ n: e.name, d: e.duration, s: e.startTime })
    }).observe({ entryTypes: ['longtask'] })
  } catch { /* not all builds expose it */ }
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__ls.push({ v: e.value, t: e.startTime })
    }).observe({ type: 'layout-shift', buffered: true })
  } catch { /* ignore */ }
}

async function longTasks(page, sinceMs = 0) {
  return page.evaluate((since) => {
    const t = (window.__lt ?? []).filter((x) => x.s >= since)
    return {
      n: t.length,
      total: t.reduce((s, x) => s + x.d, 0),
      max: t.reduce((m, x) => Math.max(m, x.d), 0),
    }
  }, sinceMs)
}

async function heap(page) {
  const m = await page.metrics()
  return { heapMB: m.JSHeapUsedSize / 1048576, nodes: m.Nodes, listeners: m.JSEventListeners }
}

async function nodeCounts(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(s)
    const count = (root) => (root ? root.querySelectorAll('*').length : 0)
    const svg = (root) => (root ? root.querySelectorAll('svg path, svg circle, svg rect, svg line, svg text').length : 0)
    const prints = q('[data-testid="intraday-prints-panel"]')
    const heat = q('[data-testid="dd-z-heatmap"]')
    return {
      documentNodes: document.querySelectorAll('*').length,
      heatmapNodes: count(heat),
      heatmapCells: document.querySelectorAll('[data-testid^="dd-z-row-"] > span:nth-child(2) > span').length,
      printsNodes: count(prints),
      printsSvgMarks: svg(prints),
      tapeRows: document.querySelectorAll('[data-testid^="dd-direction-"]').length,
    }
  })
}

const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--js-flags=--expose-gc'],
})
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100 })
  await page.evaluateOnNewDocument(OBSERVER)

  const timings = []
  const mark = (label, ms, note = '') => {
    timings.push([label, ms, note])
    console.log(`  ${label.padEnd(46)} ${fmt(ms, 0).padStart(7)} ms   ${note}`)
  }

  // ---------------------------------------------------------------- load ---
  console.log('\nFIRST PAINT OF THE TAPE (cold browser cache)')
  let t0 = Date.now()
  await page.goto(`${BASE}/usd-swaps-v2`, { waitUntil: 'domcontentloaded' })
  mark('goto -> domcontentloaded', Date.now() - t0)

  t0 = Date.now()
  await page.waitForSelector('[data-testid="trade-tape-table"]', { timeout: 180_000 })
  mark('-> tape table present', Date.now() - t0)

  t0 = Date.now()
  await page.waitForSelector('[data-testid^="dd-direction-"]', { timeout: 180_000 })
  mark('-> direction column populated', Date.now() - t0, 'the dd join is on this path')

  // dismiss the tour so it is not in the measurement
  await sleep(1000)
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')].find((x) =>
      /^(skip|close|got it|dismiss)$/i.test((x.textContent ?? '').trim()))
    b?.click()
  })
  await sleep(1200)

  const nav = await page.evaluate(() => {
    const n = performance.getEntriesByType('navigation')[0]
    const paints = Object.fromEntries(
      performance.getEntriesByType('paint').map((p) => [p.name, p.startTime]))
    return {
      ttfb: n?.responseStart, domInteractive: n?.domInteractive,
      loadEnd: n?.loadEventEnd, transfer: n?.transferSize,
      fcp: paints['first-contentful-paint'],
    }
  })
  console.log(`  navigation: TTFB ${fmt(nav.ttfb, 0)} ms · FCP ${fmt(nav.fcp, 0)} ms · `
    + `domInteractive ${fmt(nav.domInteractive, 0)} ms`)
  let lt = await longTasks(page)
  console.log(`  long tasks so far: ${lt.n}, total ${fmt(lt.total, 0)} ms, worst ${fmt(lt.max, 0)} ms`)
  let h = await heap(page)
  console.log(`  heap ${fmt(h.heapMB)} MB · ${h.nodes} DOM nodes · ${h.listeners} listeners`)

  // ------------------------------------------------------------ analytics ---
  console.log('\nOPENING THE ANALYTICS TAB (both new panels mount here)')
  const before = await page.evaluate(() => performance.now())
  t0 = Date.now()
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('button,a,div[role=tab]')]
      .find((x) => (x.textContent ?? '').trim() === 'Analytics')
    b?.click()
  })
  await page.waitForSelector('[data-testid="dd-z-heatmap"]', { timeout: 180_000 })
  mark('click -> heatmap element exists', Date.now() - t0)

  t0 = Date.now()
  await page.waitForFunction(
    () => {
      const r = document.querySelector('[data-testid^="dd-z-row-"]')
      const strip = r?.querySelector('span.flex.min-w-0.flex-1')
      return !document.querySelector('[data-testid="dd-z-strip-loading"]')
        && (strip?.children.length ?? 0) >= 10
    },
    { timeout: 180_000, polling: 100 })
  mark('-> heatmap has real columns', Date.now() - t0, '/standardised lands here')

  t0 = Date.now()
  await page.waitForFunction(
    () => {
      const p = document.querySelector('[data-testid="intraday-prints-panel"]')
      if (!p) return false
      if (/loading prints/i.test(p.textContent ?? '')) return false
      return p.querySelectorAll('svg path, svg circle').length > 5
        || /no .* prints on/i.test(p.textContent ?? '')
    },
    { timeout: 180_000, polling: 100 })
  mark('-> prints chart drawn', Date.now() - t0, '/prints: 2 round trips (rows, then grid)')

  await sleep(1500)
  lt = await longTasks(page, before)
  console.log(`  long tasks during tab open: ${lt.n}, total ${fmt(lt.total, 0)} ms, `
    + `worst ${fmt(lt.max, 0)} ms   <- this is the freeze`)
  const nc = await nodeCounts(page)
  console.log(`  DOM: ${nc.documentNodes} total · heatmap ${nc.heatmapNodes} `
    + `(${nc.heatmapCells} cells) · prints ${nc.printsNodes} (${nc.printsSvgMarks} svg marks) `
    + `· ${nc.tapeRows} tape rows`)
  h = await heap(page)
  console.log(`  heap ${fmt(h.heapMB)} MB · ${h.nodes} DOM nodes · ${h.listeners} listeners`)

  // -------------------------------------------- the busiest day, re-render ---
  console.log('\nSWITCHING TO THE BUSIEST MEASURED DAY (2025-04-09, 332 prints)')
  const b2 = await page.evaluate(() => performance.now())
  t0 = Date.now()
  await page.evaluate(() => {
    const root = document.querySelector('[data-testid="intraday-prints-panel"]')
    const inp = root?.querySelector('input[type=date]')
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
    set?.call(inp, '2025-04-09')
    inp?.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForFunction(
    () => {
      const p = document.querySelector('[data-testid="intraday-prints-panel"]')
      return (p?.querySelectorAll('svg path, svg circle').length ?? 0) > 300
    },
    { timeout: 180_000, polling: 100 })
  mark('date change -> redrawn', Date.now() - t0)
  await sleep(1200)
  lt = await longTasks(page, b2)
  console.log(`  long tasks: ${lt.n}, total ${fmt(lt.total, 0)} ms, worst ${fmt(lt.max, 0)} ms`)
  const nc2 = await nodeCounts(page)
  console.log(`  prints panel: ${nc2.printsNodes} nodes, ${nc2.printsSvgMarks} svg marks`)
  h = await heap(page)
  console.log(`  heap ${fmt(h.heapMB)} MB · ${h.nodes} DOM nodes`)

  // ------------------------------------------------- does the poll churn? ---
  console.log('\nIDLE FOR 40s — does the tape poll re-render the panels?')
  await page.evaluate(() => {
    window.__mut = { prints: 0, heat: 0, at: [] }
    const watch = (sel, key) => {
      const el = document.querySelector(sel)
      if (!el) return
      new MutationObserver((ms) => {
        window.__mut[key] += ms.length
        window.__mut.at.push([key, Math.round(performance.now())])
      }).observe(el, { childList: true, subtree: true, attributes: true, characterData: true })
    }
    watch('[data-testid="intraday-prints-panel"]', 'prints')
    watch('[data-testid="dd-z-heatmap"]', 'heat')
  })
  const b3 = await page.evaluate(() => performance.now())
  await sleep(40_000)
  const mut = await page.evaluate(() => ({
    prints: window.__mut.prints, heat: window.__mut.heat,
    firstAt: window.__mut.at.slice(0, 3), n: window.__mut.at.length,
  }))
  lt = await longTasks(page, b3)
  console.log(`  mutations in 40s idle: prints ${mut.prints}, heatmap ${mut.heat} `
    + `(${mut.n} batches)`)
  console.log(`  long tasks while idle: ${lt.n}, total ${fmt(lt.total, 0)} ms, `
    + `worst ${fmt(lt.max, 0)} ms`)
  h = await heap(page)
  console.log(`  heap after idle ${fmt(h.heapMB)} MB · ${h.nodes} DOM nodes`)

  const cls = await page.evaluate(
    () => (window.__ls ?? []).reduce((s, x) => s + x.v, 0))
  console.log(`\n  cumulative layout shift: ${fmt(cls, 3)}`)
} finally {
  await browser.close()
}
