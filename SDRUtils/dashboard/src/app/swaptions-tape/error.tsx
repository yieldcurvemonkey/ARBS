// Route-specific error boundary for the swaptions tape page.
"use client";

import { useEffect } from "react";

export default function SwaptionsTapeError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Swaptions tape error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <h2 className="text-xl font-semibold text-red-400 mb-2">
        Failed to load trade tape
      </h2>
      <p className="text-sm text-slate-400 mb-6 max-w-md">
        {error.message || "An unexpected error occurred."}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded transition-colors"
      >
        Try again
      </button>
    </div>
  );
}
