// Manual link creation dialog
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 2793-3258)

"use client";

import type { ManualLinkValidationItem } from '../../types';

export interface ManualLinksDialogProps {
  isOpen: boolean;
  selectedIds: string[];
  currentUser: string;
  onClose: () => void;
  onCreated: () => void;
}

/**
 * Modal dialog for creating manual links between trades
 * Includes validation, metrics display, and tagging
 */
export function ManualLinksDialog(props: ManualLinksDialogProps) {
  const { isOpen, selectedIds, currentUser, onClose, onCreated } = props;

  if (!isOpen) return null;

  // TODO: Extract form state (package type, link reason, comment, tags)
  // TODO: Extract validation logic and display
  // TODO: Extract metrics calculation display
  // TODO: Extract tag management UI
  // TODO: Extract create/cancel handlers

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
      <div className="bg-gray-900 rounded-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">Create Manual Link</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            ✕
          </button>
        </div>

        {/* Selected Trades */}
        <div className="mb-4">
          <p className="text-sm text-gray-400">
            Selected {selectedIds.length} trade{selectedIds.length !== 1 ? 's' : ''}
          </p>
        </div>

        {/* TODO: Add form fields */}
        {/* TODO: Add validation display */}
        {/* TODO: Add metrics display */}

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded"
          >
            Cancel
          </button>
          <button
            onClick={() => {
              // TODO: Implement create logic
              onCreated();
              onClose();
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded"
            disabled={selectedIds.length === 0}
          >
            Create Link
          </button>
        </div>
      </div>
    </div>
  );
}
