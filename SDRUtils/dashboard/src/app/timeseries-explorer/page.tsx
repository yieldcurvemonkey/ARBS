// ABOUTME: Timeseries explorer page — shows computed timeseries stored in the Supabase database.
import { Suspense } from 'react'
import TimeseriesExplorer from './TimeseriesExplorer'

export default function TimeseriesExplorerPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <TimeseriesExplorer />
    </Suspense>
  )
}
