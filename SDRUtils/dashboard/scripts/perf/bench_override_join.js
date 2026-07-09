/*
 * Read-only: verify the PROPOSED override read-path stays cheap.
 * Baseline  = current live view page.
 * Augmented = same page + a read-time LATERAL join to a sparse "active override"
 *             set (~800 member trades) that surfaces per-leg override_id and a
 *             package-level override flag WITHOUT changing package cardinality.
 * If augmented ~= baseline AND the exec_start index scan is preserved -> model holds.
 * No writes: the override set is a CTE built from a cheap PK index scan.
 */
const fs = require('fs')
const path = require('path')
const { Pool, types } = require('pg')
types.setTypeParser(1700, (v) => (v === null ? null : parseFloat(v)))
types.setTypeParser(20, (v) => (v === null ? null : parseInt(v, 10)))

function loadEnvFile(p) {
  if (!fs.existsSync(p)) return
  for (const raw of fs.readFileSync(p, 'utf8').split(/\r?\n/)) {
    const line = raw.trim(); if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('='); if (eq < 0) continue
    const key = line.slice(0, eq).trim(); let val = line.slice(eq + 1).trim()
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) val = val.slice(1, -1)
    if (process.env[key] === undefined) process.env[key] = val
  }
}
const dash = path.join(__dirname, '..', '..')
loadEnvFile(path.join(dash, '.env.local')); loadEnvFile(path.join(dash, '.env'))
function cstr() {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL
  const h = process.env.SWAPPULSE_DB_HOST ?? 'aws-0-us-east-1.pooler.supabase.com'
  const p = process.env.SWAPPULSE_DB_PORT ?? '6543'
  const d = process.env.SWAPPULSE_DB_NAME ?? 'postgres'
  const u = process.env.SWAPPULSE_DB_USER ?? 'postgres.rdobtpugtnmefxplgwyp'
  const pw = process.env.SWAPPULSE_DB_PASSWORD ?? '0rbZUh8y0Fsvdlry'
  return `postgresql://${u}:${pw}@${h}:${p}/${d}`
}
const pool = new Pool({ connectionString: cstr(), max: 4, statement_timeout: 300000 })
const PKG = 'arbs_usd_swap_tape_packages_v2', LEG = 'arbs_usd_swap_tape_legs_v2', VIEW = 'arbs_usd_swap_tape_display_v2'
const N_OV = 800, WARM = 3, TIMED = 12

function pct(a, p) { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p / 100 * s.length))] }
function st(a) { return { p50: pct(a, 50).toFixed(1), p95: pct(a, 95).toFixed(1) } }
async function t(sql) { const t0 = process.hrtime.bigint(); const r = await pool.query(sql); return { ms: Number(process.hrtime.bigint() - t0) / 1e6, rows: r.rowCount } }
function iso(ts) { return ts instanceof Date ? ts.toISOString() : String(ts) }

// active-override set as a cheap CTE (PK-index scan, ~sub-ms), simulating N_OV member trades
// AS MATERIALIZED -> Postgres builds the set ONCE (mimics a small persistent
// indexed override table hash-built once), instead of re-evaluating per LATERAL loop.
const OV_CTE = `active_ov AS MATERIALIZED (
  SELECT trade_id, ('ov-' || ((row_number() OVER (ORDER BY trade_id)) % 250)::text) AS override_id
  FROM ${LEG} ORDER BY trade_id LIMIT ${N_OV}
)`

function baselineSql(ts) {
  return `SELECT * FROM ${VIEW} d WHERE d.execution_start < '${iso(ts)}'::timestamptz ORDER BY d.execution_start DESC NULLS LAST LIMIT 200`
}
// Faithful shape: restrict to the page's packages first, resolve override membership
// ONCE over just the page's ~250 legs (hash join to the built-once override set),
// aggregate per package, join back. Mirrors a real indexed override table.
function augmentedSql(ts) {
  return `WITH ${OV_CTE},
  page AS (
    SELECT * FROM ${PKG}
    WHERE execution_start < '${iso(ts)}'::timestamptz
    ORDER BY execution_start DESC NULLS LAST LIMIT 200
  ),
  page_legs AS (
    SELECT l.package_id,
           jsonb_agg(to_jsonb(l) ORDER BY l.leg_order) AS legs_json,               -- IDENTICAL to today's view
           jsonb_object_agg(l.trade_id, av.override_id)
             FILTER (WHERE av.override_id IS NOT NULL) AS override_map,             -- sparse: empty for 99% of pkgs
           max(av.override_id) AS pkg_override_id
    FROM ${LEG} l
    JOIN page pg ON pg.package_id = l.package_id
    LEFT JOIN active_ov av ON av.trade_id = l.trade_id
    GROUP BY l.package_id
  )
  SELECT pg.*, pl.legs_json, pl.override_map, pl.pkg_override_id
  FROM page pg
  LEFT JOIN page_legs pl ON pl.package_id = pg.package_id
  ORDER BY pg.execution_start DESC NULLS LAST`
}

async function main() {
  const cur = await pool.query(`SELECT
      percentile_disc(0.99) WITHIN GROUP (ORDER BY execution_start) AS newest,
      percentile_disc(0.50) WITHIN GROUP (ORDER BY execution_start) AS mid,
      percentile_disc(0.05) WITHIN GROUP (ORDER BY execution_start) AS old
    FROM ${PKG}`)
  const c = cur.rows[0]
  const cursors = [['newest', c.newest], ['mid', c.mid], ['old', c.old]]
  console.log(`simulated active-override member trades: ${N_OV}\n`)
  console.log('cursor | baseline p50/p95 | augmented p50/p95 | overhead')
  console.log('-------|------------------|-------------------|---------')
  for (const [label, ts] of cursors) {
    const b = baselineSql(ts), a = augmentedSql(ts)
    for (let i = 0; i < WARM; i++) { await t(b); await t(a) }
    const bt = [], at = []
    for (let i = 0; i < TIMED; i++) bt.push((await t(b)).ms)
    for (let i = 0; i < TIMED; i++) at.push((await t(a)).ms)
    const bs = st(bt), as = st(at)
    const ov = ((pct(at, 50) - pct(bt, 50)) / pct(bt, 50) * 100)
    console.log(`${label.padEnd(6)} | ${bs.p50.padStart(6)}/${bs.p95.padStart(6)}ms  | ${as.p50.padStart(6)}/${as.p95.padStart(6)}ms   | ${ov >= 0 ? '+' : ''}${ov.toFixed(0)}%`)
  }

  // EXPLAIN the augmented mid page — confirm exec_start index scan preserved
  console.log('\n===== EXPLAIN (ANALYZE) augmented mid page =====')
  const ex = await pool.query(`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ${augmentedSql(c.mid)}`)
  const plan = ex.rows[0]['QUERY PLAN'][0]
  console.log(`planning: ${plan['Planning Time']}ms  execution: ${plan['Execution Time']}ms`)
  function walk(n, d) {
    const nm = n['Node Type'] + (n['Relation Name'] ? ' on ' + n['Relation Name'] : '') + (n['Index Name'] ? ' [' + n['Index Name'] + ']' : '') + (n['Subplan Name'] ? ' {' + n['Subplan Name'] + '}' : '')
    const lines = ['  '.repeat(d) + `${nm}: actual=${n['Actual Total Time']}ms loops=${n['Actual Loops']} rows=${n['Actual Rows']}`]
    for (const ch of n['Plans'] || []) lines.push(...walk(ch, d + 1))
    return lines
  }
  console.log(walk(plan.Plan, 0).join('\n'))
  await pool.end()
}
main().catch((e) => { console.error('ERR:', e.message); process.exit(1) })
