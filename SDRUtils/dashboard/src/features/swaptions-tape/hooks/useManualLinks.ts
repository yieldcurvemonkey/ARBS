// Hook for managing manual link creation and validation
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 2793-3258)

import { useCallback, useEffect, useState } from 'react';
import type { ManualLinkValidationItem } from '../types';

export interface UseManualLinksParams {
  selectedIds: string[];
  currentUser: string;
  isOpen: boolean;
}

export interface UseManualLinksReturn {
  packageType: string;
  setPackageType: (type: string) => void;
  linkReason: string;
  setLinkReason: (reason: string) => void;
  comment: string;
  setComment: (comment: string) => void;
  tags: string[];
  setTags: (tags: string[]) => void;
  tagInput: string;
  setTagInput: (input: string) => void;
  validation: ManualLinkValidationItem[];
  metrics: Record<string, any> | null;
  error: string | null;
  validating: boolean;
  submitting: boolean;
  addTag: () => void;
  removeTag: (tag: string) => void;
  validateLink: () => Promise<void>;
  handleCreate: (onCreated?: () => void, onClose?: () => void) => Promise<void>;
}

/**
 * Manages manual link creation modal state and operations
 * Handles validation, tag management, and link creation
 *
 * @param params - Selected IDs, current user, and modal state
 * @returns Link creation state and control functions
 */
export function useManualLinks(params: UseManualLinksParams): UseManualLinksReturn {
  const { selectedIds, currentUser, isOpen } = params;

  const [packageType, setPackageType] = useState('');
  const [linkReason, setLinkReason] = useState('');
  const [comment, setComment] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState('');
  const [validation, setValidation] = useState<ManualLinkValidationItem[]>([]);
  const [metrics, setMetrics] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // TODO: Extract addTag logic from lines 2844-2853
  const addTag = useCallback(() => {
    if (tagInput.trim() && !tags.includes(tagInput.trim())) {
      setTags([...tags, tagInput.trim()]);
      setTagInput('');
    }
  }, [tagInput, tags]);

  // TODO: Extract removeTag logic from lines 2855-2857
  const removeTag = useCallback((tag: string) => {
    setTags(tags.filter((t) => t !== tag));
  }, [tags]);

  // TODO: Extract validateLink logic from lines 2859-2892
  const validateLink = useCallback(async () => {
    if (selectedIds.length === 0) return;

    setValidating(true);
    setError(null);

    try {
      const res = await fetch('/api/swaption/links', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_ids: selectedIds,
          package_type: packageType || null,
          link_reason: linkReason || null,
          user_comment: comment || null,
          tags: tags.length > 0 ? tags : null,
          created_by: currentUser,
          validate_only: true,
        }),
      });

      if (!res.ok) throw new Error(`Validation failed: ${res.statusText}`);

      const data = await res.json();
      setValidation(data.validation || []);
      setMetrics(data.metrics || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Validation error');
    } finally {
      setValidating(false);
    }
  }, [selectedIds, packageType, linkReason, comment, tags, currentUser]);

  // TODO: Extract handleCreate logic from lines 2894-2938
  const handleCreate = useCallback(
    async (onCreated?: () => void, onClose?: () => void) => {
      if (selectedIds.length === 0) return;

      setSubmitting(true);
      setError(null);

      try {
        const res = await fetch('/api/swaption/links', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trade_ids: selectedIds,
            package_type: packageType || null,
            link_reason: linkReason || null,
            user_comment: comment || null,
            tags: tags.length > 0 ? tags : null,
            created_by: currentUser,
          }),
        });

        if (!res.ok) throw new Error(`Creation failed: ${res.statusText}`);

        onCreated?.();
        onClose?.();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Creation error');
      } finally {
        setSubmitting(false);
      }
    },
    [selectedIds, packageType, linkReason, comment, tags, currentUser]
  );

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setPackageType('');
      setLinkReason('');
      setComment('');
      setTags([]);
      setTagInput('');
      setValidation([]);
      setMetrics(null);
      setError(null);
    }
  }, [isOpen]);

  // Auto-validate when modal opens
  useEffect(() => {
    if (isOpen && selectedIds.length > 0) {
      validateLink();
    }
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
  };
}
