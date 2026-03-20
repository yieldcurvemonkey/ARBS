// ABOUTME: Curve explorer page — shows what curves are stored in the Supabase database.
import { Suspense } from 'react'
import CurveExplorer from './CurveExplorer'

export default function CurveExplorerPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <CurveExplorer />
    </Suspense>
  )
}
