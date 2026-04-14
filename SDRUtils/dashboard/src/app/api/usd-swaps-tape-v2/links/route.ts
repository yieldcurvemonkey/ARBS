// ABOUTME: Re-export of manual-link POST/GET from the shared swap-links handler.
// Tape v2 shares the arbs_usd_swap_manual_links_v2 table with the legacy
// USD swap route tree, so we simply forward the HTTP verbs.
export { GET, POST } from '../../usd-swap/links/route'
