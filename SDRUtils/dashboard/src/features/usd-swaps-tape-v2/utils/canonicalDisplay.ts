// ABOUTME: Display-side translator for the Phase 4
// canonical_underlier_key column. The Python canonicaliser at
// SDRUtils/core/underlier_canonical.py emits stable slash-separated
// keys like "USD/SOFR-OIS/COMPOUND"; this module turns those into
// human labels for the UI and surfaces example SDR-feed source
// strings for tooltips so analysts can audit the bucket contents.

export type CanonicalBucket = {
  /** Canonical key, identical to what canonical_underlier_key() returns. */
  key: string
  /** Short label for chips / column cells. */
  label: string
  /** Long label for tooltips / panel headers. */
  longLabel: string
  /**
   * Example raw-SDR strings that the Python canonicaliser collapses
   * into this bucket. Non-exhaustive — add as new variants are
   * spotted in the wild.
   */
  sourceVariants: readonly string[]
}

export const CANONICAL_BUCKETS: readonly CanonicalBucket[] = [
  {
    key: 'USD/SOFR-OIS/COMPOUND',
    label: 'SOFR OIS',
    longLabel: 'USD SOFR (daily compounded OIS)',
    sourceVariants: [
      'USD-SOFR-COMPOUND 1D Constant',
      'USD-SOFR-OIS Compound 1D',
      'USD-SOFR-OIS Compound 1D Constant',
      'USD-SOFR-OIS-COMPOUND',
      'USD-SOFR Compound',
      'USD-SOFR',
    ],
  },
  {
    key: 'USD/SOFR-TERM',
    label: 'Term SOFR',
    longLabel: 'CME Term SOFR (forward-looking term rate)',
    sourceVariants: [
      'USD-SOFR-CME-TERM 1M',
      'USD-SOFR-CME-TERM 3M',
      'USD-SOFR-CME-TERM 6M',
      'USD-SOFR TERM 3M',
      'CME-TS-1M',
      'CME-TS-3M',
    ],
  },
  {
    key: 'USD/FED-FUNDS-OIS/COMPOUND',
    label: 'Fed Funds OIS',
    longLabel: 'USD Federal Funds (daily compounded OIS)',
    sourceVariants: [
      'USD-Federal Funds-OIS Compound 1D',
      'USD-Federal Funds-H.15-OIS-COMPOUND 1D',
      'USD-FED-FUNDS-OIS',
      'USD-FED FUNDS-H.15',
      'USD-FF-OIS',
    ],
  },
  {
    key: 'USD/OBFR-OIS/COMPOUND',
    label: 'OBFR OIS',
    longLabel: 'USD Overnight Bank Funding Rate (NY Fed) OIS',
    sourceVariants: [
      'USD-Overnight Bank Funding-OIS Compound 1D',
      'USD-OBFR-OIS-COMPOUND',
      'USD-OBFR',
    ],
  },
  {
    key: 'USD/BSBY/IBOR',
    label: 'BSBY',
    longLabel: 'Bloomberg Short-Term Bank Yield Index',
    sourceVariants: [
      'USD-BSBY-1M',
      'USD-BSBY-3M',
      'USD-BSBY-6M',
      'BSBY 3M',
    ],
  },
  {
    key: 'USD/LIBOR/IBOR',
    label: 'USD LIBOR',
    longLabel: 'USD LIBOR (legacy + synthetic)',
    sourceVariants: [
      'USD-LIBOR-BBA-3M',
      'USD-LIBOR-BBA-6M',
      'USD-LIBOR-ICE-3M',
      'SYN-LIBOR-1M',
      'SYN-LIBOR-3M',
      'SYN-LIBOR-6M',
    ],
  },
  {
    key: 'USD/ISDA-CMS',
    label: 'CMS',
    longLabel: 'USD ISDA Constant-Maturity Swap rate',
    sourceVariants: [
      'USD-ISDA Swap Rate-11:00 NY-10Y',
      'USD-CMS-10Y',
    ],
  },
  {
    key: 'USD/SIFMA-MUNI',
    label: 'SIFMA Muni',
    longLabel: 'SIFMA Municipal Swap Index',
    sourceVariants: [
      'USD-SIFMA Municipal Swap Index',
      'USD-BMA',
    ],
  },
] as const

const KEY_TO_BUCKET = new Map<string, CanonicalBucket>(
  CANONICAL_BUCKETS.map((b) => [b.key, b]),
)

const SHORT_NAME_OVERRIDES: Record<string, string> = {
  'SOFR-OIS': 'SOFR',
  'FED-FUNDS-OIS': 'Fed Funds',
  'OBFR-OIS': 'OBFR',
  BSBY: 'BSBY',
  LIBOR: 'LIBOR',
  'ISDA-CMS': 'CMS',
  'SIFMA-MUNI': 'SIFMA',
  'SOFR-TERM': 'Term SOFR',
}

function shortenLeg(canonLeg: string): string {
  return SHORT_NAME_OVERRIDES[canonLeg] ?? canonLeg
}

export function canonicalDisplayLabel(key: string): string {
  if (!key || key === 'UNKNOWN') return '—'
  const direct = KEY_TO_BUCKET.get(key)
  if (direct) return direct.label
  if (key.startsWith('USD/BASIS/')) {
    const [legA, legB] = key.slice('USD/BASIS/'.length).split('+')
    if (legA && legB) {
      return `${shortenLeg(legA)} vs ${shortenLeg(legB)} (basis)`
    }
  }
  return key
}

export function canonicalLongLabel(key: string): string {
  if (!key || key === 'UNKNOWN') return 'Unknown / unrecognised underlier'
  return KEY_TO_BUCKET.get(key)?.longLabel ?? key
}

export function canonicalSourceVariants(key: string): readonly string[] {
  return KEY_TO_BUCKET.get(key)?.sourceVariants ?? []
}
