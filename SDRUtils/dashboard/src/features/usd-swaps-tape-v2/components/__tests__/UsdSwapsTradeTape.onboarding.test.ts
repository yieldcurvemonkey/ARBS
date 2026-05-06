// ABOUTME: Source-level contract tests for the USD swaps tape first-visit
// onboarding guide. The orchestrator has heavy Next/PrimeReact wiring, so
// these tests pin the storage gate, manual entry point, and guide content.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const tapeSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx',
  ),
  'utf8',
)

const guideSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/UsdSwapsOnboardingGuide.tsx',
  ),
  'utf8',
)

describe('UsdSwapsTradeTape onboarding gate', () => {
  it('uses a versioned localStorage key for first-visit state', () => {
    expect(guideSource).toMatch(
      /'usd-swaps-tape-v2:onboarding-seen:v1'/,
    )
    expect(guideSource).toMatch(/storage\.getItem/)
    expect(guideSource).toMatch(/storage\.setItem/)
  })

  it('auto-opens only when the user has not already seen the guide', () => {
    expect(tapeSource).toMatch(
      /if\s*\(\s*hasSeenUsdSwapsOnboarding\(window\.localStorage\)\s*\)\s*return/,
    )
    expect(tapeSource).toMatch(/setOnboardingOpen\(true\)/)
  })

  it('persists seen state when the guide closes', () => {
    expect(tapeSource).toMatch(
      /const closeOnboarding = useCallback\([\s\S]{0,300}markUsdSwapsOnboardingSeen\(window\.localStorage\)/,
    )
  })

  it('keeps a manual How to use entry point in the tape toolbar', () => {
    expect(tapeSource).toMatch(/<HelpCircle\b/)
    expect(tapeSource).toMatch(/onClick=\{openOnboarding\}/)
    expect(tapeSource).toMatch(/How to use/)
  })

  it('mounts the guide with controlled open and close props', () => {
    expect(tapeSource).toMatch(/<UsdSwapsOnboardingGuide\b/)
    expect(tapeSource).toMatch(/open=\{onboardingOpen\}/)
    expect(tapeSource).toMatch(/onClose=\{closeOnboarding\}/)
  })
})

describe('UsdSwapsOnboardingGuide content', () => {
  it('renders as a step-by-step guide', () => {
    expect(guideSource).toMatch(/Step \{stepIndex \+ 1\} of \{STEPS\.length\}/)
    expect(guideSource).toMatch(/Next/)
    expect(guideSource).toMatch(/Back/)
    expect(guideSource).toMatch(/Done/)
  })

  it('covers the core dashboard workflows concisely', () => {
    expect(guideSource).toMatch(/Start with the volume grid/)
    expect(guideSource).toMatch(/Scan and narrow the tape/)
    expect(guideSource).toMatch(/Open package context/)
    expect(guideSource).toMatch(/Select trades for workups/)
    expect(guideSource).toMatch(/Use analytics when needed/)
  })
})
