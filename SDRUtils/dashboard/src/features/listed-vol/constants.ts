import type {
  ListedVolExpiry,
  ListedVolProduct,
  ListedVolProductClass,
  ListedVolRange
} from './types'

export const UST_PRODUCTS: ListedVolProduct[] = ['TU', 'FV', 'TY', 'UXY', 'US', 'WN']
export const STIR_PRODUCTS: ListedVolProduct[] = ['SFR']
export const ALL_LISTED_VOL_PRODUCTS: ListedVolProduct[] = [...UST_PRODUCTS, ...STIR_PRODUCTS]

export const ROLLING_EXPIRIES: ListedVolExpiry[] = ['1W', '2W', '1M', '2M', '3M', '6M']

export const PRODUCT_SWAP_TENOR: Record<ListedVolProduct, string> = {
  TU: '2Y',
  FV: '5Y',
  TY: '10Y',
  US: '20Y',
  WN: '30Y',
  UXY: '10Y',
  SFR: '1Y'
}

export const PRODUCT_CLASS_LABELS: Record<ListedVolProductClass, string> = {
  UST: 'UST',
  STIR: 'STIR',
  ALL: 'All'
}

export const LISTED_VOL_RANGE_OPTIONS: ListedVolRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

export const LISTED_VOL_LOOKBACK_SESSIONS = 63
