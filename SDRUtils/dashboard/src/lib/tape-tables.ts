// ABOUTME: Single source of truth for which tape generation the dashboard reads.
// The _v2 tape is written by the `run_swaptape` cron job on the host `sky` and
// serves a different front end. ARBS owns _v3.
//
// This constant is deliberately independent of the Python writer's
// TAPE_GENERATION, and deliberately a constant rather than an env var:
// pointing the reader back at v2 to inspect what sky produces must never
// resurrect ARBS *writes* to v2, and a missing env var must never silently
// select the wrong generation.

export const TAPE_GENERATION = 'v3'

const t = (base: string) => `arbs_usd_swap_${base}_${TAPE_GENERATION}`

export const TAPE_PACKAGES = t('tape_packages')
export const TAPE_LEGS = t('tape_legs')
export const TAPE_DISPLAY = t('tape_display')
export const TAPE_OVERRIDES = t('tape_overrides')
export const TAPE_OVERRIDE_MEMBERS = t('tape_override_members')
export const TAPE_OVERRIDE_HISTORY = t('tape_override_history')
export const TAPE_NOTES = t('tape_notes')
export const TAPE_SIGNAL = t('tape_signal')

// Not versioned: keyed by its own UUID, shared with the classification stage.
export const MANUAL_LINKS = 'arbs_usd_swap_manual_links_v2'
