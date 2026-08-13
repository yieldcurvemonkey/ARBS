// ABOUTME: WHY does switching the prints chart to the busiest day take 12s?
//
// The server call for 2025-04-09 is 76ms warm and the payload is 407KB. The
// interaction measured 11,979ms with 3,639ms of long tasks and heap 110 -> 245
// MB. So the cost is on the client, and guessing which part would be exactly
// the sort of plausible-sounding answer that wastes a day.
//
// This takes a real CPU profile across the interaction and aggregates SELF time
// by function, plus a network breakdown so the wait is separated from the work.
import { createRequire } from 'node:module'
const require = createRequire('C:/Users/chris/clee/ARBS-fe/SDRUtils/dashboard/package.json')
const puppeteer = require('puppeteer')

const BASE = process.argv[2] ?? 'http://localhost:3100'
const DAY = process.argv[3] ?? '2025-04-09'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1680, height: 1100 })

  const net = []
  page.on('requestfinished', async (r) => {
    try {
      const t = r.timing?.() ?? null
      const resp = r.response()
      if (!r.url().includes('/api/')) return
      net.push({
        url: r.url().replace(BASE, '').slice(0, 70),
        status: resp?.status(),
        ms: t ? Math.round(t.receiveHeadersEnd - t.requestTime * 0 || 0) : null,
      })
    } catch { /* ignore */ }
  })

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
  await page.waitForSelector('[data-testid="intraday-prints-panel"]', { timeout: 180_000 })
  await page.waitForFunction(
    () => {
      const p = document.querySelector('[data-testid="intraday-prints-panel"]')
      return p && !/loading prints/i.test(p.textContent ?? '')
        && p.querySelectorAll('svg path, svg circle').length > 5
    }, { timeout: 180_000, polling: 100 })
  await sleep(2500)

  // ------------------------------------------------------------- profile ---
  const client = await page.createCDPSession()
  await client.send('Profiler.enable')
  await client.send('Profiler.setSamplingInterval', { interval: 200 })
  await client.send('Profiler.start')

  net.length = 0
  const t0 = Date.now()
  await page.evaluate((d) => {
    const root = document.querySelector('[data-testid="intraday-prints-panel"]')
    const inp = root?.querySelector('input[type=date]')
    const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set
    set?.call(inp, d)
    inp?.dispatchEvent(new Event('change', { bubbles: true }))
  }, DAY)
  await page.waitForFunction(
    () => (document.querySelector('[data-testid="intraday-prints-panel"]')
      ?.querySelectorAll('svg path, svg circle').length ?? 0) > 300,
    { timeout: 300_000, polling: 50 })
  const wall = Date.now() - t0
  await sleep(600)
  const { profile } = await client.send('Profiler.stop')

  // ---------------------------------------------------------- aggregate ----
  const byId = new Map(profile.nodes.map((n) => [n.id, n]))
  const self = new Map()
  const total = profile.samples?.length ?? 0
  const dur = (profile.endTime - profile.startTime) / 1000
  for (const s of profile.samples ?? []) {
    const n = byId.get(s)
    if (!n) continue
    const f = n.callFrame
    const name = `${f.functionName || '(anonymous)'}  ${(f.url || '').split('/').pop()}:${f.lineNumber}`
    self.set(name, (self.get(name) ?? 0) + 1)
  }
  const msPerSample = dur / Math.max(total, 1)

  console.log(`\nDATE CHANGE -> ${DAY}`)
  console.log(`  wall clock          ${wall} ms`)
  console.log(`  profile duration    ${dur.toFixed(0)} ms over ${total} samples`)
  console.log(`\n  API calls during the interaction:`)
  for (const n of net) console.log(`    ${n.status}  ${n.url}`)

  console.log(`\n  TOP SELF TIME (sampled)`)
  const rows = [...self.entries()].sort((a, b) => b[1] - a[1]).slice(0, 22)
  for (const [name, c] of rows) {
    const ms = c * msPerSample
    if (ms < 15) continue
    console.log(`    ${(ms).toFixed(0).padStart(6)} ms  ${(c / total * 100).toFixed(1).padStart(5)}%  ${name}`)
  }

  // idle vs busy
  const idle = [...self.entries()]
    .filter(([n]) => n.startsWith('(idle)') || n.startsWith('(program)'))
    .reduce((s, [, c]) => s + c, 0)
  console.log(`\n  (idle)+(program) = ${(idle * msPerSample).toFixed(0)} ms `
    + `of ${dur.toFixed(0)} ms -> actual JS work ${((total - idle) * msPerSample).toFixed(0)} ms`)

  const nc = await page.evaluate(() => {
    const p = document.querySelector('[data-testid="intraday-prints-panel"]')
    return {
      panelNodes: p?.querySelectorAll('*').length,
      svgAll: p?.querySelectorAll('svg *').length,
      paths: p?.querySelectorAll('svg path').length,
      surfaces: p?.querySelectorAll('svg').length,
      recharts: p?.querySelectorAll('.recharts-wrapper').length,
      layers: p?.querySelectorAll('.recharts-layer').length,
    }
  })
  console.log(`\n  DOM after: ${JSON.stringify(nc)}`)
} finally {
  await browser.close()
}
