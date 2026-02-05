// ABOUTME: USD Swaptions SDR Trade Tape dashboard entry point.
import { Suspense } from "react";

import SwaptionTradeTape from "@/features/swaptions-tape/components/SwaptionTradeTape";

export default function SwaptionsTapePage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <SwaptionTradeTape />
    </Suspense>
  );
}
