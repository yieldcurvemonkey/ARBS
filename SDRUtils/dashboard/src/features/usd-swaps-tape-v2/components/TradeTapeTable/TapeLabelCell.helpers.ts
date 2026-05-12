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

export function displayTapeLabel(row: UsdSwapTapeRow): string {
  const labels = [row.tape_label, row.legs_json?.[0]?.tape_label]
  for (const label of labels) {
    if (typeof label === 'string' && label.trim().length > 0) {
      return stripExecutionTags(label.trim())
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
const TENOR_SEGMENT_RE =
  /(FOMC\s+[A-Z]{3,4}\d{2})|(\bIMM_[A-Z]\d{4}\b)|(\bSpot\b)|(\b\d+D\b(?!\s+Constant))|(\b\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/\d+(?:\.\d+)?[YMW](?:\d+[YMW])?)*)/g

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
