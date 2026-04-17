import { EMPTY_VALUE } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

export function displayTapeLabel(row: UsdSwapTapeRow): string {
  const labels = [row.tape_label, row.legs_json?.[0]?.tape_label]
  for (const label of labels) {
    if (typeof label === 'string' && label.trim().length > 0) {
      return label.trim()
    }
  }
  return EMPTY_VALUE
}

// Match tenor-style segments so TapeLabelCell can bold them:
//   - FOMC anchor: "FOMC APR26"
//   - Outright tenor: "5Y", "18M", "5Y11M", "1.5Y"
//   - Curve / fly package tenors: "5Y/10Y", "2Y/5Y/30Y"
const TENOR_SEGMENT_RE =
  /(FOMC\s+[A-Z]{3,4}\d{2})|(\d+(?:\.\d+)?[YMW](?:\d+[YMW])?(?:\/\d+(?:\.\d+)?[YMW](?:\d+[YMW])?)*)/g

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
