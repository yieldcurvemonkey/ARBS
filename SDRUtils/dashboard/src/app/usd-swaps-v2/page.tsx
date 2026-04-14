import { Suspense } from 'react'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape-v2'

export default function UsdSwapsV2Page() {
  return (
    <Suspense
      fallback={<div className="p-4 text-sm text-slate-400">Loading tape…</div>}
    >
      <UsdSwapsTradeTape />
    </Suspense>
  )
}
