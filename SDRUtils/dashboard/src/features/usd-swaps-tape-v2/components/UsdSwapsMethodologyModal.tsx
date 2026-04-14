'use client'
// ABOUTME: Methodology modal describing TradeTape enrichment + clean_tape semantics.
import type { JSX } from 'react'
import { Dialog } from 'primereact/dialog'

export interface UsdSwapsMethodologyModalProps {
  open: boolean
  onClose: () => void
}

export function UsdSwapsMethodologyModal(
  props: UsdSwapsMethodologyModalProps,
): JSX.Element {
  return (
    <Dialog
      visible={props.open}
      onHide={props.onClose}
      header="Tape methodology"
      style={{ width: 640 }}
      modal
    >
      <div className="flex flex-col gap-3 text-sm text-slate-200">
        <section>
          <h2 className="text-base font-semibold mb-1">Enrichment pipeline</h2>
          <p className="text-slate-300">
            Every CFTC SDR USD swap trade flows through{' '}
            <code className="font-mono text-slate-100">TradeTape.compute()</code>,
            which adds ~60 columns spanning classification, lifecycle, quality,
            package structure, FOMC context, and temporal clustering before
            persistence.
          </p>
        </section>
        <section>
          <h2 className="text-base font-semibold mb-1">Clean Tape preset</h2>
          <p className="text-slate-300">
            Clean Tape hides lifecycle noise: unwinds, compressions, reset
            optimizations, novation terminations, clearing terminations, and
            UFRO (off-market coupon) trades. NEW_RISK, TERMINATION (non-comp),
            NOVATION_BORN, CORRECTION, and EXERCISE_BORN remain.
          </p>
        </section>
        <section>
          <h2 className="text-base font-semibold mb-1">Tape label</h2>
          <p className="text-slate-300">
            The hero identifier combines ANNA DSB UPI attributes (index, reset
            frequency, notional schedule, delivery type) with forward/tenor and
            package structure. Off-date trades carry a <code>~</code> prefix.
          </p>
        </section>
        <section>
          <h2 className="text-base font-semibold mb-1">Design reference</h2>
          <p className="text-slate-300">
            <code className="font-mono">
              docs/plans/2026-04-14-usd-swaps-tape-v2-design.md
            </code>
          </p>
        </section>
      </div>
    </Dialog>
  )
}
