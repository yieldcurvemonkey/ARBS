import { Suspense } from 'react'

import ListedVolDashboard from '@/features/listed-vol/components/ListedVolDashboard'

export default function ListedVsOtcPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <ListedVolDashboard />
    </Suspense>
  )
}
