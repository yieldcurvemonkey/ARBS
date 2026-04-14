// Manual-link types mirror the legacy Sofr swap types, which in turn come
// from the shared arbs_usd_swap_manual_links_v2 table.
export type {
  ManualSwapLinkValidationStatus,
  ManualSwapLinkValidationItem,
  ManualSwapLinkTrade,
  ManualSwapLinkHistoryItem,
  ManualSwapLinkDetail,
} from '@/features/sofr-swaps-tape/types'

export type ManualLink = {
  link_id: string
  manual_package_id: string
  package_type: string | null
  linked_trade_ids: string[]
  created_by: string
  created_at: string
  user_comment: string | null
  link_reason: string | null
  tags: string[] | null
  link_metrics: Record<string, any> | null
  is_active: boolean
}
