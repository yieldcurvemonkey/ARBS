// ABOUTME: Legacy Vol Grid route retained as a redirect to the nested USD Rates Vol Analytics section.
import { redirect } from 'next/navigation'

export default function VolGridPage() {
  redirect('/usd-rates-vol-analytics/atmf-vol-grid')
}
