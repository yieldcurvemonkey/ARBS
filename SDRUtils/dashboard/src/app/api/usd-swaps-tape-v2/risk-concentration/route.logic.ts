export const GROUPABLE = {
  tape_label: 'l.tape_label',
  trade_type: 'l.trade_type',
  venue: 'l.venue',
  ccp: 'l.ccp',
  session: 'l.execution_session',
  tenor: 'l.tenor_label',
  rate_index: 'l.rate_index_clean',
  fomc_meeting: 'l.fomc_meeting_label',
} as const

export type GroupByKey = keyof typeof GROUPABLE

export function buildRiskConcentrationSql(
  groupBy: GroupByKey,
  clean: boolean,
): string {
  const expr = GROUPABLE[groupBy]
  const whereClean = clean
    ? ` AND NOT l.is_unwind AND NOT l.is_compression AND NOT l.is_ufro AND NOT l.is_reset_optimization`
    : ''
  return `
    SELECT ${expr} AS value,
           COUNT(*)::int AS trade_count,
           SUM(l.risk)::float AS total_dv01,
           SUM(l.notional)::float AS total_notional
    FROM arbs_usd_swap_tape_legs_v2 l
    WHERE l.as_of_date = $1::date
    ${whereClean}
      AND ${expr} IS NOT NULL
    GROUP BY ${expr}
    ORDER BY ABS(SUM(l.risk)) DESC NULLS LAST
    LIMIT 30
  `
}
