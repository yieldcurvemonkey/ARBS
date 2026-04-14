// ABOUTME: USD swaps SDR trade tape dashboard entry point.
import { Suspense } from 'react'
import Link from 'next/link'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape/components/UsdSwapsTradeTape'

export default function UsdSwapsPage() {
  return (
    <>
      <div className="px-3 py-2 bg-emerald-950/40 text-emerald-200 text-sm border-b border-emerald-800 flex items-center justify-between">
        <span>
          A lifecycle-complete tape is available at{' '}
          <Link href="/usd-swaps-v2" className="underline">
            /usd-swaps-v2
          </Link>{' '}
          during soak — feedback welcome.
        </span>
        <Link
          href="/usd-swaps-v2"
          className="text-xs px-2 py-1 rounded bg-emerald-900/60 hover:bg-emerald-800/80 text-emerald-50"
        >
          Try the new tape →
        </Link>
      </div>
      <Suspense
        fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}
      >
        <UsdSwapsTradeTape />
      </Suspense>
    </>
  )
}
