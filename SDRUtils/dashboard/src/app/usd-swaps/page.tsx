// ABOUTME: USD swaps SDR trade tape dashboard entry point.
import { Suspense } from 'react'
import UsdSwapsTradeTape from '@/features/usd-swaps-tape/components/UsdSwapsTradeTape'

export default function UsdSwapsPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <UsdSwapsTradeTape />
    </Suspense>
  )
}
