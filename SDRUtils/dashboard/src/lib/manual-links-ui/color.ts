// ABOUTME: Deterministic linkId -> HSL colour for manual-link row chips.
// Used by both swaptions-tape and usd-swaps-tape-v2 so a linked group of
// trades shares a stable colour across renders. The hash is intentionally
// simple - 1-in-256 visual collisions are acceptable; disambiguation is
// provided by the link-ID label and package-ID alongside the dot.

/**
 * Map a manual link id to an HSL colour string.
 *
 * Returns null for empty / null / undefined inputs so callers can branch
 * on the result without sentinel checks (this preserves the original
 * swaptions behaviour exactly).
 */
export function manualLinkColor(linkId?: string | null): string | null {
  if (!linkId) return null;
  let hash = 0;
  for (let i = 0; i < linkId.length; i += 1) {
    hash = (hash * 31 + linkId.charCodeAt(i)) % 360;
  }
  return `hsl(${hash}, 65%, 52%)`;
}
