import { EMPTY_VALUE, TAPE_TAG_TONES } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

const EXECUTION_TAGS = new Set(Object.keys(TAPE_TAG_TONES))
const EXECUTION_TAG_RE = new RegExp(
  `\\b(${[...EXECUTION_TAGS].sort((a, b) => b.length - a.length).join('|')})\\b`,
  'g',
)

export function stripExecutionTags(label: string): string {
  return label.replace(EXECUTION_TAG_RE, '').replace(/\s{2,}/g, ' ').trim()
}

export function extractExecutionTags(label: string): string[] {
  const tags: string[] = []
  const re = new RegExp(EXECUTION_TAG_RE.source, 'g')
  let m: RegExpExecArray | null
  while ((m = re.exec(label)) !== null) {
    if (!tags.includes(m[1])) tags.push(m[1])
  }
  return tags
}

export function collapseTenors(
  label: string,
  nLegs: number | null | undefined,
): string {
  // 5+ slash-separated tenor tokens: always collapse regardless of structure
  const re5 =
    /[~-]?\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/[~-]?\d+(?:\.\d+)?[YMW](?:\d+[YMW])?){4,}/g
  let collapsed = label.replace(re5, (match) => {
    const count = nLegs ?? match.split('/').length
    return `PKG-${count}`
  })
  // 2-4 slash-separated tenors followed by "Package": collapse PKG-2/3/4.
  // CURVE ("5Y/10Y CURVE") and FLY ("2Y/5Y/30Y FLY") are not affected
  // because their structure word is not "Package".
  const re2 =
    /[~-]?\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/[~-]?\d+(?:\.\d+)?[YMW](?:\d+[YMW])?){1,3}(?=\s+Package\b)/g
  collapsed = collapsed.replace(re2, (match) => {
    const count = nLegs ?? match.split('/').length
    return `PKG-${count}`
  })
  // Drop redundant "Package" trade-type word right after PKG-N
  return collapsed.replace(/PKG-(\d+)\s+Package\b/g, 'PKG-$1')
}

/**
 * Truncate a slash-joined MMYY alias when it has more than `max` segments.
 * "0330/0530/0730/0930/1130" → "0330/0530/0730/…+2"
 */
function collapseAlias(label: string, max = 4): string {
  // Match a run of slash-separated 4-digit tokens (MMYY aliases).
  return label.replace(/\b(\d{4}(?:\/\d{4}){4,})\b/g, (match) => {
    const parts = match.split('/')
    if (parts.length <= max) return match
    return parts.slice(0, max - 1).join('/') + `/…+${parts.length - (max - 1)}`
  })
}

export function displayTapeLabel(row: UsdSwapTapeRow): string {
  // Prefer the UST-alias label ("…Spot 0536/0546 CURVE MMS PHYS") when present.
  // Non-MMS rows have tape_label_ust_alias == tape_label, so this is a no-op for
  // them; rows ingested before the column existed fall through to tape_label.
  const labels = [
    row.tape_label_ust_alias,
    row.tape_label,
    row.legs_json?.[0]?.tape_label_ust_alias,
    row.legs_json?.[0]?.tape_label,
  ]
  for (const label of labels) {
    if (typeof label === 'string' && label.trim().length > 0) {
      const stripped = stripExecutionTags(label.trim())
      return collapseAlias(collapseTenors(stripped, row.n_package_legs))
    }
  }
  return EMPTY_VALUE
}

// Match the forward / tenor / anchor segments so TapeLabelCell can bold them:
//   - FOMC meeting anchor: "FOMC APR26"
//   - IMM contract anchor: "IMM_M2026", "IMM_H2027" (month code + 4-digit
//     year, e.g. H/M/U/Z for Mar/Jun/Sep/Dec)
//   - Literal forward "Spot"
//   - Day-count forward start: "74D", "70D" (note: the reset-frequency "1D
//     Constant" token must NOT match — negative lookahead for " Constant"
//     skips it while still catching true forward-start days)
//   - Outright tenor: "5Y", "18M", "5Y11M", "1.5Y"
//   - Curve / fly package tenors: "5Y/10Y", "2Y/5Y/30Y"
//   - MMS UST-maturity alias (numeric MMYY): "0236", "0536/0546" (placed after
//     the FOMC/IMM anchors so those win; 4-digit MMYY does not collide with any
//     other token in these labels)
const TENOR_SEGMENT_RE =
  /(PKG-\d+)|(FOMC\s+[A-Z]{3,4}\d{2})|(\bIMM_[A-Z]\d{4}\b)|(\bSpot\b)|(\b\d+D\b(?!\s+Constant))|(\b\d{2}\d{2}(?:\/\d{2}\d{2})*\b)|(\b\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/\d+(?:\.\d+)?[YMW](?:\d+[YMW])?)*)/g

export interface TapeLabelSegment {
  text: string
  isTenor: boolean
}

export function parseTapeLabelSegments(label: string): TapeLabelSegment[] {
  if (!label || label === EMPTY_VALUE) {
    return [{ text: label || '', isTenor: false }]
  }
  const segments: TapeLabelSegment[] = []
  const regex = new RegExp(TENOR_SEGMENT_RE.source, 'g')
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(label)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: label.slice(lastIndex, match.index), isTenor: false })
    }
    segments.push({ text: match[0], isTenor: true })
    lastIndex = regex.lastIndex
  }
  if (lastIndex < label.length) {
    segments.push({ text: label.slice(lastIndex), isTenor: false })
  }
  if (segments.length === 0) {
    segments.push({ text: label, isTenor: false })
  }
  return segments
}
