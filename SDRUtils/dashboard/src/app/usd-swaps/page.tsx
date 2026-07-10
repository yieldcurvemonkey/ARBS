// ABOUTME: USD swaps SDR trade tape dashboard entry point — v2 cutover.
import { Suspense } from 'react'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape-v2'

export default function UsdSwapsPage() {
  return (
    <Suspense
      fallback={<div className="p-4 text-sm text-slate-400">Loading tape…</div>}
    >
      <div className="-mx-4 -mb-6 -mt-6 flex flex-col h-full">
        <UsdSwapsTradeTape />
      </div>
    </Suspense>
  )
}
