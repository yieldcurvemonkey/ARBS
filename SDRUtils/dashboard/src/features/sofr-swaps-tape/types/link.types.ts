// Manual swap link types. The shared shapes live in
// lib/manual-links-ui/types; sofr extends `Trade` with risk + fixed_rate
// fields that downstream PnL calculators consume.

import type {
  ManualLinkDetail,
  ManualLinkHistoryItem,
  ManualLinkValidationItem,
  ManualLinkValidationStatus,
} from '@/lib/manual-links-ui/types'

export type ManualSwapLinkValidationStatus = ManualLinkValidationStatus
export type ManualSwapLinkValidationItem = ManualLinkValidationItem
export type ManualSwapLinkHistoryItem = ManualLinkHistoryItem
export type ManualSwapLinkDetail = ManualLinkDetail

// Sofr-specific trade extension: shared base + sofr-only risk/fixed_rate.
export type ManualSwapLinkTrade = {
  trade_id: string
  package_id: string
  trade_label?: string | null
  product_type?: string | null
  notional?: number | null
  risk?: number | null
  fixed_rate?: number | null
  execution_timestamp?: string | null
  platform_identifier?: string | null
}
