// ABOUTME: Redirect shim — /usd-swaps-v2 now lives at /usd-swaps after cutover.
import { redirect } from 'next/navigation'

export default function UsdSwapsV2Page() {
  redirect('/usd-swaps')
}
