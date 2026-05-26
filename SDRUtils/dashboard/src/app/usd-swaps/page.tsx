// ABOUTME: USD swaps SDR trade tape dashboard entry point — v2 cutover.
import { Suspense } from 'react'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape-v2'

// The shared root layout wraps <main> in `mx-auto max-w-[120rem] px-4 py-6`,
// which steals ~56px of vertical space and squeezes the tape well inside the
// viewport. The trade tape wants every pixel it can get, so bust out of the
// main container's padding with negative margins and size the tape to fill
// the viewport below the top nav (≈ 4.25rem on this layout).
export default function UsdSwapsPage() {
  return (
    <Suspense
      fallback={<div className="p-4 text-sm text-slate-400">Loading tape…</div>}
    >
      <div
        className="-mx-4 -mb-10 -mt-6 flex flex-col"
        style={{ height: 'calc(300vh - 4.25rem)' }}
      >
        <UsdSwapsTradeTape />
      </div>
    </Suspense>
  )
}
