// App-wide error boundary. Catches unhandled errors in nested routes.
"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <h2 className="text-xl font-semibold text-red-400 mb-2">
        Something went wrong
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
