'use client'

import type { ListedVolProduct } from '../types'

type ProductSelectorProps = {
  products: ListedVolProduct[]
  selectedProduct: ListedVolProduct
  onSelect: (product: ListedVolProduct) => void
}

export function ProductSelector({
  products,
  selectedProduct,
  onSelect
}: ProductSelectorProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {products.map((product) => {
        const active = product === selectedProduct
        return (
          <button
            key={product}
            type="button"
            onClick={() => onSelect(product)}
            className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
              active
                ? 'border-sky-400 bg-sky-500/15 text-sky-100'
                : 'border-slate-700 bg-slate-900/70 text-slate-300 hover:border-slate-500 hover:text-white'
            }`}
          >
            {product}
          </button>
        )
      })}
    </div>
  )
}
