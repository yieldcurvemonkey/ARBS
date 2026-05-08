'use client'
// ABOUTME: First-visit onboarding guide for the USD swaps tape dashboard.
import type { JSX } from 'react'
import { useEffect, useState } from 'react'
import {
  BarChart3,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Filter,
  Link2,
  MousePointerClick,
  PanelBottomOpen,
  Rows3,
  type LucideIcon,
} from 'lucide-react'
import { Dialog } from 'primereact/dialog'
import { useIsMobile } from '@/lib/hooks/useIsMobile'

export const USD_SWAPS_ONBOARDING_STORAGE_KEY =
  'usd-swaps-tape-v2:onboarding-seen:v1'
const STORAGE_SEEN_VALUE = 'seen'

export function hasSeenUsdSwapsOnboarding(
  storage: Pick<Storage, 'getItem'>,
): boolean {
  return (
    storage.getItem(USD_SWAPS_ONBOARDING_STORAGE_KEY) === STORAGE_SEEN_VALUE
  )
}

export function markUsdSwapsOnboardingSeen(
  storage: Pick<Storage, 'setItem'>,
): void {
  storage.setItem(USD_SWAPS_ONBOARDING_STORAGE_KEY, STORAGE_SEEN_VALUE)
}

type OnboardingStep = {
  title: string
  body: string
  detail: string
  icon: LucideIcon
  accentClassName: string
}

const STEPS: OnboardingStep[] = [
  {
    title: 'Start with the volume grid',
    body: 'Use the top grid as the market map. Hotter cells point to where package activity is concentrated.',
    detail: 'Click a cell to filter the tape to the packages behind that expiry and tenor bucket.',
    icon: BarChart3,
    accentClassName: 'bg-sky-500/10 text-sky-200 ring-sky-400/30',
  },
  {
    title: 'Scan and narrow the tape',
    body: 'Sort by the headers and use the funnel icons for per-column filters.',
    detail: 'Reset filters clears every column filter when the view gets too narrow.',
    icon: Filter,
    accentClassName: 'bg-cyan-500/10 text-cyan-200 ring-cyan-400/30',
  },
  {
    title: 'Open package context',
    body: 'Use the row chevron to inspect legs without leaving the tape.',
    detail: 'Manual-link badges open the package audit modal when a row is already linked.',
    icon: Rows3,
    accentClassName: 'bg-amber-500/10 text-amber-200 ring-amber-400/30',
  },
  {
    title: 'Select trades for workups',
    body: 'Checking rows focuses the first selected package and enables manual linking.',
    detail: 'Link selected appears only when at least one row is selected.',
    icon: Link2,
    accentClassName: 'bg-emerald-500/10 text-emerald-200 ring-emerald-400/30',
  },
  {
    title: 'Use analytics when needed',
    body: 'The analytics dock follows the focused or selected trade so the tape and charts stay in sync.',
    detail: 'Show Analytics opens the dock; clearing focus also clears the table selection.',
    icon: PanelBottomOpen,
    accentClassName: 'bg-indigo-500/10 text-indigo-200 ring-indigo-400/30',
  },
]

export interface UsdSwapsOnboardingGuideProps {
  open: boolean
  onClose: () => void
}

export function UsdSwapsOnboardingGuide(
  props: UsdSwapsOnboardingGuideProps,
): JSX.Element {
  const isMobile = useIsMobile()
  const [stepIndex, setStepIndex] = useState(0)

  useEffect(() => {
    if (props.open) setStepIndex(0)
  }, [props.open])

  const step = STEPS[stepIndex]
  const Icon = step.icon
  const isFirst = stepIndex === 0
  const isLast = stepIndex === STEPS.length - 1

  return (
    <Dialog
      visible={props.open}
      onHide={props.onClose}
      header="How to use the USD swaps tape"
      style={isMobile ? { width: '100%', maxWidth: '100%' } : { width: 560, maxWidth: 'calc(100vw - 2rem)' }}
      modal
      draggable={false}
      resizable={false}
      data-testid="usd-swaps-onboarding-guide"
    >
      <div className="flex flex-col gap-4 text-sm text-slate-200">
        <div className="flex items-start gap-3 rounded border border-slate-800 bg-slate-950/80 p-3 shadow-inner transition-colors">
          <div
            className={`mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded ring-1 ${step.accentClassName}`}
          >
            <Icon className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <div className="mb-1 font-mono text-[10px] uppercase text-slate-500">
              Step {stepIndex + 1} of {STEPS.length}
            </div>
            <h2 className="text-base font-semibold text-slate-100">
              {step.title}
            </h2>
            <p className="mt-1 text-sm leading-5 text-slate-300">
              {step.body}
            </p>
            <p className="mt-2 rounded border border-slate-800 bg-slate-900/80 px-2.5 py-2 text-xs leading-5 text-slate-400">
              {step.detail}
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <div
            className="flex items-center gap-1"
            aria-label="Onboarding progress"
          >
            {STEPS.map((item, index) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setStepIndex(index)}
                className={`h-1.5 rounded-full transition-all ${
                  index === stepIndex
                    ? 'w-6 bg-sky-300'
                    : 'w-1.5 bg-slate-700 hover:bg-slate-500'
                }`}
                aria-label={`Go to step ${index + 1}`}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={props.onClose}
              className="inline-flex items-center gap-1 rounded border border-slate-700 px-2.5 py-1.5 font-mono text-[11px] text-slate-300 hover:bg-slate-800"
            >
              <MousePointerClick className="h-3.5 w-3.5" aria-hidden="true" />
              Skip
            </button>
            <button
              type="button"
              disabled={isFirst}
              onClick={() => setStepIndex((index) => Math.max(0, index - 1))}
              className="inline-flex items-center gap-1 rounded border border-slate-700 px-2.5 py-1.5 font-mono text-[11px] text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Back
            </button>
            <button
              type="button"
              onClick={() => {
                if (isLast) {
                  props.onClose()
                  return
                }
                setStepIndex((index) => Math.min(STEPS.length - 1, index + 1))
              }}
              className="inline-flex items-center gap-1 rounded bg-sky-700 px-3 py-1.5 font-mono text-[11px] text-sky-50 hover:bg-sky-600"
            >
              {isLast ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  Done
                </>
              ) : (
                <>
                  Next
                  <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
