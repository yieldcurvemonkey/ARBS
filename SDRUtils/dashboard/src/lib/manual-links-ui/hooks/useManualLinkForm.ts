// ABOUTME: State machine for the manual-link create flow. Manages the
// editable form (package type, link reason, comment, tags), surfaces
// validation items + computed metrics from the server, and exposes the
// create POST. Auto-validates on dialog open. Replaces the per-consumer
// minimal hook in usd-swaps-tape-v2 and the in-component state in
// swaptions-tape with a single shared implementation.

import { useCallback, useEffect, useState } from 'react';
import { createManualLinkApi } from '../api/manualLinkApi';
import type {
  ManualLinkValidationItem,
} from '../types';

export interface UseManualLinkFormParams {
  /** Base path of the manual-links API for this consumer. */
  basePath: string;
  /** Trade ids the user has selected for the create flow. */
  selectedIds: string[];
  /** The user creating the link (sent as `created_by`). */
  currentUser: string;
  /** Modal open state - drives auto-validate + reset. */
  isOpen: boolean;
  /** Initial package_type value (defaults to ''). */
  initialPackageType?: string;
  /** Initial link_reason value (defaults to ''). */
  initialLinkReason?: string;
  /** Optional manual_package_id to pin (used by usd-swaps-tape-v2). */
  manualPackageId?: string;
}

export interface UseManualLinkFormReturn {
  packageType: string;
  setPackageType: (value: string) => void;
  linkReason: string;
  setLinkReason: (value: string) => void;
  comment: string;
  setComment: (value: string) => void;
  tags: string[];
  setTags: (tags: string[]) => void;
  tagInput: string;
  setTagInput: (input: string) => void;
  validation: ManualLinkValidationItem[];
  metrics: Record<string, unknown> | null;
  error: string | null;
  validating: boolean;
  submitting: boolean;
  addTag: () => void;
  removeTag: (tag: string) => void;
  validateLink: () => Promise<void>;
  handleCreate: (
    onCreated?: (result: { link_id: string; manual_package_id: string }) => void,
    onClose?: () => void,
  ) => Promise<void>;
  reset: () => void;
}

export function useManualLinkForm(
  params: UseManualLinkFormParams,
): UseManualLinkFormReturn {
  const {
    basePath,
    selectedIds,
    currentUser,
    isOpen,
    initialPackageType = '',
    initialLinkReason = '',
    manualPackageId,
  } = params;

  const [packageType, setPackageType] = useState(initialPackageType);
  const [linkReason, setLinkReason] = useState(initialLinkReason);
  const [comment, setComment] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [validation, setValidation] = useState<ManualLinkValidationItem[]>([]);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const addTag = useCallback(() => {
    const next = tagInput.trim();
    if (!next) return;
    setTags((prev) => (prev.includes(next) ? prev : [...prev, next]));
    setTagInput('');
  }, [tagInput]);

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((item) => item !== tag));
  }, []);

  const reset = useCallback(() => {
    setPackageType(initialPackageType);
    setLinkReason(initialLinkReason);
    setComment('');
    setTags([]);
    setTagInput('');
    setValidation([]);
    setMetrics(null);
    setError(null);
  }, [initialLinkReason, initialPackageType]);

  const validateLink = useCallback(async () => {
    if (selectedIds.length < 2) return;
    setValidating(true);
    setError(null);
    try {
      const api = createManualLinkApi(basePath);
      const out = await api.validateLink({
        trade_ids: selectedIds,
        package_type: packageType || undefined,
        link_reason: linkReason || undefined,
        user_comment: comment || undefined,
        comment: comment || undefined,
        tags: tags.length ? tags : undefined,
        created_by: currentUser,
        user: currentUser,
        manual_package_id: manualPackageId,
      });
      setValidation(out.validation);
      setMetrics(out.metrics);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to validate manual link.';
      setError(msg);
    } finally {
      setValidating(false);
    }
  }, [basePath, comment, currentUser, linkReason, manualPackageId, packageType, selectedIds, tags]);

  const handleCreate = useCallback(
    async (
      onCreated?: (result: { link_id: string; manual_package_id: string }) => void,
      onClose?: () => void,
    ) => {
      if (selectedIds.length < 2) return;
      setSubmitting(true);
      setError(null);
      try {
        const api = createManualLinkApi(basePath);
        const result = await api.createLink({
          trade_ids: selectedIds,
          package_type: packageType || undefined,
          link_reason: linkReason || undefined,
          user_comment: comment || undefined,
          comment: comment || undefined,
          tags: tags.length ? tags : undefined,
          created_by: currentUser,
          user: currentUser,
          manual_package_id: manualPackageId,
        });
        onCreated?.(result);
        onClose?.();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : 'Failed to create manual link.';
        setError(msg);
      } finally {
        setSubmitting(false);
      }
    },
    [basePath, comment, currentUser, linkReason, manualPackageId, packageType, selectedIds, tags],
  );

  // Reset state on open/close transitions and auto-validate when there
  // are at least 2 selected ids on open.
  useEffect(() => {
    if (!isOpen) {
      reset();
      return;
    }
    if (selectedIds.length >= 2) {
      void validateLink();
    }
    // intentionally only depend on isOpen / selectedIds.length so we
    // don't re-fire on tag/comment edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, selectedIds.length]);

  return {
    packageType,
    setPackageType,
    linkReason,
    setLinkReason,
    comment,
    setComment,
    tags,
    setTags,
    tagInput,
    setTagInput,
    validation,
    metrics,
    error,
    validating,
    submitting,
    addTag,
    removeTag,
    validateLink,
    handleCreate,
    reset,
  };
}
