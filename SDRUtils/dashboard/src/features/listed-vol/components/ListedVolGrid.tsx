'use client'

import { ROLLING_EXPIRIES } from '../constants'
import type {
  ListedVolDisplayMode,
  ListedVolGridCell as ListedVolGridCellType,
  ListedVolProduct
} from '../types'
import { ListedVolGridCell } from './ListedVolGridCell'

type ListedVolGridProps = {
  products: ListedVolProduct[]
  cells: ListedVolGridCellType[]
  mode: ListedVolDisplayMode
  onCellClick: (cell: ListedVolGridCellType) => void
}

export function ListedVolGrid({
  products,
  cells,
  mode,
  onCellClick
}: ListedVolGridProps) {
  const cellMap = new Map(cells.map((cell) => [`${cell.product}_${cell.expiryLabel}`, cell]))

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-950/70">
      <table className="min-w-full border-collapse">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/80">
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
              Product
            </th>
            {ROLLING_EXPIRIES.map((expiry) => (
              <th
                key={expiry}
                className="px-2 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-400"
              >
                {expiry}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <tr key={product} className="border-b border-slate-900/80 last:border-b-0">
              <th className="w-24 px-4 py-3 text-left text-sm font-semibold text-slate-100">
                {product}
              </th>
              {ROLLING_EXPIRIES.map((expiry) => {
                const cell = cellMap.get(`${product}_${expiry}`) ?? null
                return (
                  <td key={`${product}_${expiry}`} className="min-w-[150px] p-2">
                    {cell ? (
                      <ListedVolGridCell
                        cell={cell}
                        mode={mode}
                        onClick={() => onCellClick(cell)}
                      />
                    ) : (
                      <div className="flex min-h-[84px] items-center justify-center border border-dashed border-slate-800 bg-slate-950/60 text-sm text-slate-500">
                        --
                      </div>
                    )}
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
