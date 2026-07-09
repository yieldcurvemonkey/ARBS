/*
 * Read-only benchmark of the USD swaps tape display view.
 * Goal: quantify per-page latency across a wide historical range, and isolate
 * the LATERAL leg-aggregation cost share, to decide materialize y/n.
 *
 * Mirrors db.ts connection resolution. Runs ONLY SELECT / EXPLAIN. No writes.
 */
const fs = require('fs')
const path = require('path')
const { Pool, types } = require('pg')

types.setTypeParser(1700, (v) => (v === null ? null : parseFloat(v)))
types.setTypeParser(20, (v) => (v === null ? null : parseInt(v, 10)))

// ---- load env files like Next (.env.local wins over .env) ----
function loadEnvFile(p) {
  if (!fs.existsSync(p)) return
  const txt = fs.readFileSync(p, 'utf8')
  for (const raw of txt.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 0) continue
    const key = line.slice(0, eq).trim()
    let val = line.slice(eq + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1)
    }
    if (process.env[key] === undefined) process.env[key] = val
  }
}
const dash = path.join(__dirname, '..', '..')
loadEnvFile(path.join(dash, '.env.local'))
loadEnvFile(path.join(dash, '.env'))

function resolveConnectionString() {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL
  const host = process.env.SWAPPULSE_DB_HOST ?? 'aws-0-us-east-1.pooler.supabase.com'
  const port = process.env.SWAPPULSE_DB_PORT ?? '6543'
  const dbname = process.env.SWAPPULSE_DB_NAME ?? 'postgres'
  const user = process.env.SWAPPULSE_DB_USER ?? 'postgres.rdobtpugtnmefxplgwyp'
  const password = process.env.SWAPPULSE_DB_PASSWORD ?? '0rbZUh8y0Fsvdlry'
  return `postgresql://${user}:${password}@${host}:${port}/${dbname}`
}

const cs = resolveConnectionString()
// redacted host/port for logging
try {
  const u = new URL(cs)
  console.log(`[conn] host=${u.hostname} port=${u.port} db=${u.pathname.slice(1)}`)
} catch { console.log('[conn] (unparsed connection string)') }

const pool = new Pool({ connectionString: cs, max: 4, idleTimeoutMillis: 10000, statement_timeout: 300000 })

const PKG = 'arbs_usd_swap_tape_packages_v2'
const LEG = 'arbs_usd_swap_tape_legs_v2'
const VIEW = 'arbs_usd_swap_tape_display_v2'
const LIMIT = 200
const WARMUP = 3
const TIMED = 15

function pct(arr, p) {
  const s = [...arr].sort((a, b) => a - b)
  const idx = Math.min(s.length - 1, Math.floor((p / 100) * s.length))
  return s[idx]
}
function stats(arr) {
  return {
    n: arr.length,
    min: Math.min(...arr).toFixed(1),
    p50: pct(arr, 50).toFixed(1),
    p95: pct(arr, 95).toFixed(1),
    max: Math.max(...arr).toFixed(1),
  }
}
async function timeQuery(sql) {
  const t0 = process.hrtime.bigint()
  const res = await pool.query(sql)
  const t1 = process.hrtime.bigint()
  return { ms: Number(t1 - t0) / 1e6, rows: res.rowCount }
}

async function main() {
  // ---- metadata ----
  const meta = await pool.query(`
    SELECT
      (SELECT count(*) FROM ${PKG}) AS n_pkgs,
      (SELECT count(*) FROM ${LEG}) AS n_legs,
      (SELECT min(execution_start) FROM ${PKG}) AS min_ts,
      (SELECT max(execution_start) FROM ${PKG}) AS max_ts
  `)
  const m = meta.rows[0]
  console.log('\n===== METADATA =====')
  console.log(`packages : ${m.n_pkgs}`)
  console.log(`legs     : ${m.n_legs}`)
  console.log(`legs/pkg : ${(m.n_legs / m.n_pkgs).toFixed(2)}`)
  console.log(`date span: ${m.min_ts?.toISOString?.() ?? m.min_ts}  ->  ${m.max_ts?.toISOString?.() ?? m.max_ts}`)

  // indexes on packages (for deep-page reasoning)
  const idx = await pool.query(
    `SELECT indexname, indexdef FROM pg_indexes WHERE tablename = $1 ORDER BY indexname`, [PKG]
  )
  console.log('\n----- indexes on packages -----')
  for (const r of idx.rows) console.log(`  ${r.indexname}: ${r.indexdef.replace(/^CREATE (UNIQUE )?INDEX \S+ ON \S+ USING /, '')}`)

  // manual_links table size (sparse override sanity)
  try {
    const ml = await pool.query(`SELECT count(*) AS n, count(*) FILTER (WHERE is_active) AS active FROM arbs_usd_swap_manual_links_v2`)
    console.log(`\nmanual_links: total=${ml.rows[0].n} active=${ml.rows[0].active}`)
  } catch (e) { console.log(`\nmanual_links: (not readable: ${e.message})`) }

  // ---- cursor percentiles across history ----
  const cur = await pool.query(`
    SELECT
      percentile_disc(0.00) WITHIN GROUP (ORDER BY execution_start) AS p00,
      percentile_disc(0.20) WITHIN GROUP (ORDER BY execution_start) AS p20,
      percentile_disc(0.40) WITHIN GROUP (ORDER BY execution_start) AS p40,
      percentile_disc(0.60) WITHIN GROUP (ORDER BY execution_start) AS p60,
      percentile_disc(0.80) WITHIN GROUP (ORDER BY execution_start) AS p80,
      percentile_disc(0.99) WITHIN GROUP (ORDER BY execution_start) AS p99
    FROM ${PKG}
  `)
  const c = cur.rows[0]
  // Order newest->oldest so cursor = "page starting below this ts"
  const cursors = [
    ['newest(p99)', c.p99],
    ['p80', c.p80],
    ['p60', c.p60],
    ['p40', c.p40],
    ['p20', c.p20],
    ['oldest(p00)', c.p00],
  ]

  function iso(ts) { return ts instanceof Date ? ts.toISOString() : String(ts) }
  function fullSql(ts) {
    return `SELECT * FROM ${VIEW} d WHERE d.execution_start < '${iso(ts)}'::timestamptz ORDER BY d.execution_start DESC NULLS LAST LIMIT ${LIMIT}`
  }
  function noLegsSql(ts) {
    return `SELECT package_id, execution_start FROM ${PKG} WHERE execution_start < '${iso(ts)}'::timestamptz ORDER BY execution_start DESC NULLS LAST LIMIT ${LIMIT}`
  }

  console.log('\n===== PER-PAGE BENCHMARK (LIMIT ' + LIMIT + ') =====')
  console.log('cursor        | fullView cold | fullView warm p50/p95 | pkgOnly warm p50/p95 | LATERAL share (warm p50)')
  console.log('--------------|---------------|-----------------------|----------------------|-------------------------')

  const allFullWarm = []
  const allNoLegsWarm = []
  for (const [label, ts] of cursors) {
    if (ts == null) { console.log(`${label}: no timestamp`); continue }
    const fsql = fullSql(ts)
    const nsql = noLegsSql(ts)
    // cold (first hit) for full view
    const cold = await timeQuery(fsql)
    // warmup
    for (let i = 0; i < WARMUP; i++) { await timeQuery(fsql); await timeQuery(nsql) }
    // timed
    const full = [], nol = []
    for (let i = 0; i < TIMED; i++) { full.push((await timeQuery(fsql)).ms) }
    for (let i = 0; i < TIMED; i++) { nol.push((await timeQuery(nsql)).ms) }
    allFullWarm.push(...full); allNoLegsWarm.push(...nol)
    const fS = stats(full), nS = stats(nol)
    const share = ((pct(full, 50) - pct(nol, 50)) / pct(full, 50) * 100)
    console.log(
      `${label.padEnd(13)} | ${cold.ms.toFixed(0).padStart(9)}ms (${cold.rows}r) | ` +
      `${fS.p50.padStart(6)}/${fS.p95.padStart(6)}ms       | ` +
      `${nS.p50.padStart(6)}/${nS.p95.padStart(6)}ms      | ` +
      `${share.toFixed(0)}%`
    )
  }

  console.log('\n----- OVERALL (all cursors pooled, warm) -----')
  console.log('fullView :', JSON.stringify(stats(allFullWarm)))
  console.log('pkgOnly  :', JSON.stringify(stats(allNoLegsWarm)))
  const ovShare = ((pct(allFullWarm, 50) - pct(allNoLegsWarm, 50)) / pct(allFullWarm, 50) * 100)
  console.log(`LATERAL+transfer share of full read (p50): ${ovShare.toFixed(0)}%`)

  // ---- EXPLAIN ANALYZE on a mid-history page to attribute node time ----
  const midTs = c.p60
  console.log('\n===== EXPLAIN (ANALYZE, BUFFERS) on p60 page =====')
  const ex = await pool.query(`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ${fullSql(midTs)}`)
  const plan = ex.rows[0]['QUERY PLAN'][0]
  console.log(`planning: ${plan['Planning Time']}ms  execution: ${plan['Execution Time']}ms`)
  // walk plan, print node actual times
  function walk(node, depth) {
    const lines = []
    const name = node['Node Type'] + (node['Relation Name'] ? ' on ' + node['Relation Name'] : '') + (node['Subplan Name'] ? ' [' + node['Subplan Name'] + ']' : '')
    lines.push('  '.repeat(depth) + `${name}: actual=${node['Actual Total Time']}ms loops=${node['Actual Loops']} rows=${node['Actual Rows']}`)
    for (const ch of node['Plans'] || []) lines.push(...walk(ch, depth + 1))
    return lines
  }
  console.log(walk(plan.Plan, 0).join('\n'))

  await pool.end()
}

main().catch((e) => { console.error('BENCH ERROR:', e); process.exit(1) })
