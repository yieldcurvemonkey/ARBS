// ABOUTME: The render half of the hand-traced sign test.
//
// Reads THE SAME committed fixture as tests/test_dealer_direction_sign_trace.py
// (tests/data/dd_sign_trace.json, produced by scratch/ddfe07_sign_trace.py
// against the real materialised tables), so the Python and TypeScript halves of
// the trace cannot drift apart.
//
// The Python half pins tape row -> DB row. This pins DB row -> rendered word:
// the dd_* columns exactly as the tape route aliases them, through
// directionView, to the word and the tone a reader sees.
//
// Every assertion names a side. A comparative assertion survives a global flip.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  DIRECTION_AMBER,
  DIRECTION_SKY,
  DIRECTION_TONES,
  directionView,
} from '../dealerDirection'

const here = dirname(fileURLToPath(import.meta.url))
// src/features/usd-swaps-tape-v2/utils/__tests__ -> repo root is six up from
// `src`, i.e. dashboard/ -> SDRUtils/ -> repo/
const FIXTURE = join(here, '..', '..', '..', '..', '..', '..', '..',
  'tests', 'data', 'dd_sign_trace.json')

type Trace = {
  package_id: string
  dealer_direction: 'RECEIVED' | 'PAID'
  dealer_sign: number
  p: number
  signed_weight: number
  deviation_bps: number
  mid_bias_bps: number
  tau_bps: number
  rule: string
  total_delta_dv01: number
  total_dv01_if_received: number
}

let trace: Trace | null = null
try {
  trace = JSON.parse(readFileSync(FIXTURE, 'utf-8')) as Trace
} catch {
  trace = null
}

const maybe = trace ? describe : describe.skip

maybe('the traced trade renders the word the DB stored', () => {
  it('carries the fixture through directionView unchanged', () => {
    const t = trace!
    // Exactly the shape the tape route aliases onto a row.
    const view = directionView({
      dd_dealer_direction: t.dealer_direction,
      dd_dealer_sign: t.dealer_sign,
      dd_p: t.p,
      dd_signed_weight: t.signed_weight,
      dd_rule: t.rule,
      dd_deviation_bps: t.deviation_bps,
      dd_tau_bps: t.tau_bps,
      dd_total_delta_dv01: t.total_delta_dv01,
      dd_total_dv01_if_received: t.total_dv01_if_received,
      dd_exclusion_reason: null,
    })

    expect(view.known).toBe(true)
    expect(view.reason).toBeNull()

    if (t.dealer_direction === 'RECEIVED') {
      expect(t.dealer_sign).toBe(1)
      expect(t.signed_weight).toBeGreaterThan(0)
      expect(t.total_delta_dv01).toBeGreaterThan(0)
      expect(view.label).toBe('RCVD')
      expect(view.tone).toBe('received')
      expect(DIRECTION_TONES[view.tone]).toContain('sky')
      expect(view.title).toContain('Dealer RECEIVED fixed')
      expect(view.title).toContain('long duration')
      expect(view.title).not.toContain('short duration')
    } else {
      expect(t.dealer_sign).toBe(-1)
      expect(t.signed_weight).toBeLessThan(0)
      expect(t.total_delta_dv01).toBeLessThan(0)
      expect(view.label).toBe('PAID')
      expect(view.tone).toBe('paid')
      expect(DIRECTION_TONES[view.tone]).toContain('amber')
      expect(view.title).toContain('Dealer PAID fixed')
      expect(view.title).toContain('short duration')
      expect(view.title).not.toContain('long duration')
    }
  })

  it('the MIRROR of the traced trade renders the other word', () => {
    // The assertion a global sign flip cannot survive: the same machinery,
    // fed the opposite sign, must produce the opposite word and the other hue.
    const t = trace!
    const mirrored = directionView({
      dd_dealer_direction: t.dealer_direction === 'RECEIVED' ? 'PAID' : 'RECEIVED',
      dd_dealer_sign: -t.dealer_sign,
      dd_p: 1 - t.p,
      dd_signed_weight: -t.signed_weight,
      dd_rule: t.rule,
    })
    const real = directionView({
      dd_dealer_direction: t.dealer_direction,
      dd_dealer_sign: t.dealer_sign,
      dd_p: t.p,
      dd_signed_weight: t.signed_weight,
      dd_rule: t.rule,
    })
    expect(mirrored.label).not.toBe(real.label)
    expect(mirrored.tone).not.toBe(real.tone)
    expect(new Set([mirrored.label, real.label])).toEqual(new Set(['RCVD', 'PAID']))
    expect(new Set([mirrored.tone, real.tone])).toEqual(
      new Set(['received', 'paid']))
    // and conviction is a magnitude, so it does NOT flip
    expect(mirrored.conviction).toBeCloseTo(real.conviction!, 12)
  })

  it('quotes the traced p and weight in the tooltip, to three places', () => {
    const t = trace!
    const view = directionView({
      dd_dealer_direction: t.dealer_direction,
      dd_dealer_sign: t.dealer_sign,
      dd_p: t.p,
      dd_signed_weight: t.signed_weight,
    })
    expect(view.title).toContain(`p(customer paid fixed) = ${t.p.toFixed(3)}`)
    expect(view.title).toContain(`weight 2p-1 = ${t.signed_weight.toFixed(3)}`)
  })

  it('the two poles are the CVD-safe pair', () => {
    expect(DIRECTION_SKY).toBe('#38bdf8')
    expect(DIRECTION_AMBER).toBe('#f59e0b')
  })
})

// A skipped suite is invisible in a green run, so say so out loud.
if (!trace) {
  describe('the sign trace fixture', () => {
    it('IS MISSING — run scratch/ddfe07_sign_trace.py after a publish', () => {
      expect(trace).toBeNull()
    })
  })
}
