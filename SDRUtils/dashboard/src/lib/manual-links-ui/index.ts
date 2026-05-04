// ABOUTME: Barrel export for the manual-links-ui shared module. Public
// surface used by both swaptions-tape and usd-swaps-tape-v2.

export { manualLinkColor } from './color';
export { isManualPackage } from './predicates';
export { groupLinkedRows } from './grouping';
export type {
  TapeRowLike,
  ManualLinkValidationStatus,
  ManualLinkValidationItem,
  ManualLinkTrade,
  ManualLinkHistoryItem,
  ManualLinkDetail,
  ManualLinkDetailBundle,
} from './types';
