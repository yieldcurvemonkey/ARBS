import type { SwaptionExpiry, SwaptionTail, UstfExpiry, UstfProduct } from './types'

export const USTF_PRODUCTS: UstfProduct[] = ['TU', 'FV', 'TY', 'TN', 'US', 'UL']

export const SWAPTION_TAILS: SwaptionTail[] = ['2Y', '5Y', '7Y', '10Y', '20Y', '30Y']

export const USTF_EXPIRIES: UstfExpiry[] = ['1W', '2W', '1M', '2M', '3M', '6M']

export const SWAPTION_EXPIRIES: SwaptionExpiry[] = ['1M', '3M', '6M', '1Y']

export const USTF_SWAP_TAIL_MAP: Record<UstfProduct, SwaptionTail> = {
  TU: '2Y',
  FV: '5Y',
  TY: '7Y',
  TN: '10Y',
  US: '20Y',
  UL: '30Y',
}

export const USTF_PRODUCT_LABELS: Record<UstfProduct, string> = {
  TU: 'TU (2Y)',
  FV: 'FV (5Y)',
  TY: 'TY (7Y)',
  TN: 'TN (10Y)',
  US: 'US (20Y)',
  UL: 'UL (30Y)',
}

export const SERIES_COLORS = [
  '#38bdf8', // sky-400
  '#fb7185', // rose-400
  '#34d399', // emerald-400
  '#fbbf24', // amber-400
  '#a78bfa', // violet-400
  '#f472b6', // pink-400
]

export const STANDARD_PAIRS: Array<{
  label: string
  series1: { type: 'ustf'; product: UstfProduct; expiry: UstfExpiry }
  series2: { type: 'swaption'; expiry: SwaptionExpiry; tail: SwaptionTail }
}> = [
  {
    label: '1M TY vs 1Mx7Y',
    series1: { type: 'ustf', product: 'TY', expiry: '1M' },
    series2: { type: 'swaption', expiry: '1M', tail: '7Y' },
  },
  {
    label: '3M TY vs 3Mx7Y',
    series1: { type: 'ustf', product: 'TY', expiry: '3M' },
    series2: { type: 'swaption', expiry: '3M', tail: '7Y' },
  },
  {
    label: '1M FV vs 1Mx5Y',
    series1: { type: 'ustf', product: 'FV', expiry: '1M' },
    series2: { type: 'swaption', expiry: '1M', tail: '5Y' },
  },
  {
    label: '1M US vs 1Mx20Y',
    series1: { type: 'ustf', product: 'US', expiry: '1M' },
    series2: { type: 'swaption', expiry: '1M', tail: '20Y' },
  },
  {
    label: '1M TU vs 1Mx2Y',
    series1: { type: 'ustf', product: 'TU', expiry: '1M' },
    series2: { type: 'swaption', expiry: '1M', tail: '2Y' },
  },
  {
    label: '1M UL vs 1Mx30Y',
    series1: { type: 'ustf', product: 'UL', expiry: '1M' },
    series2: { type: 'swaption', expiry: '1M', tail: '30Y' },
  },
]
