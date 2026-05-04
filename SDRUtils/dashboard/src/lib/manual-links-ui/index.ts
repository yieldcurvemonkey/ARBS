// ABOUTME: Barrel export for the manual-links-ui shared module. Public
// surface used by both swaptions-tape and usd-swaps-tape-v2.

export { manualLinkColor } from './color';
export { isManualPackage } from './predicates';
export { groupLinkedRows } from './grouping';
export { ManualLinkBadge } from './components/ManualLinkBadge';
export type { ManualLinkBadgeProps } from './components/ManualLinkBadge';
export { ManualLinkValidationList } from './components/ManualLinkValidationList';
export { ManualLinkMetricsTable } from './components/ManualLinkMetricsTable';
export { ManualLinkHistoryTable } from './components/ManualLinkHistoryTable';
export { ManualLinkDetailModal } from './components/ManualLinkDetailModal';
export type {
  ManualLinkDetailModalProps,
  Option as ManualLinkOption,
} from './components/ManualLinkDetailModal';
export { useManualLinkDetails } from './hooks/useManualLinkDetails';
export type {
  UseManualLinkDetailsOptions,
  UseManualLinkDetailsState,
} from './hooks/useManualLinkDetails';
export { useManualLinkForm } from './hooks/useManualLinkForm';
export type {
  UseManualLinkFormParams,
  UseManualLinkFormReturn,
} from './hooks/useManualLinkForm';
export { createManualLinkApi } from './api/manualLinkApi';
export type {
  ManualLinkApiClient,
  CreateLinkBody,
  UpdateLinkBody,
  ListLinksQuery,
} from './api/manualLinkApi';
export type {
  TapeRowLike,
  ManualLinkValidationStatus,
  ManualLinkValidationItem,
  ManualLinkTrade,
  ManualLinkHistoryItem,
  ManualLinkDetail,
  ManualLinkDetailBundle,
} from './types';
