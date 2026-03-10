'use client'

import { ALL_LISTED_VOL_PRODUCTS, ROLLING_EXPIRIES } from '../constants'
import type { ListedVolProductClass, ListedVolRealizedRow } from '../types'
import { formatRatio, formatVol } from '../utils'

type RealizedVolPanelProps = {
  rows: ListedVolRealizedRow[]
  productClass: ListedVolProductClass
}

export function RealizedVolPanel({
  rows,
  productClass
}: RealizedVolPanelProps) {
  const products =
    productClass === 'UST'
      ? ALL_LISTED_VOL_PRODUCTS.filter((product) => product !== 'SFR')
      : productClass === 'STIR'
        ? ['SFR']
        : ALL_LISTED_VOL_PRODUCTS
  const rowMap = new Map(rows.map((row) => [`${row.product}_${row.windowLabel}`, row]))

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950/70">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/80">
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
              Product
            </th>
            {ROLLING_EXPIRIES.map((windowLabel) => (
              <th
                key={windowLabel}
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400"
              >
                {windowLabel}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product} className="border-b border-slate-900/80 last:border-b-0">
              <th className="px-4 py-3 text-left text-sm font-semibold text-slate-100">{product}</th>
              {ROLLING_EXPIRIES.map((windowLabel) => {
                const row = rowMap.get(`${product}_${windowLabel}`) ?? null
                return (
                  <td key={`${product}_${windowLabel}`} className="px-4 py-3 align-top">
                    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                      <div className="text-lg font-semibold tabular-nums text-slate-100">
                        {formatVol(row?.realizedNvolBps ?? null)}
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        Imp/Real {formatRatio(row?.impliedRealizedRatio ?? null)}
                      </div>
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
