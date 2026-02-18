// ABOUTME: USD SOFR swaps SDR trade tape dashboard entry point.
import { Suspense } from 'react'
import SofrSwapsTradeTape from '@/features/sofr-swaps-tape/components/SofrSwapsTradeTape'

export default function SofrSwapsPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <SofrSwapsTradeTape />
    </Suspense>
  )
}
