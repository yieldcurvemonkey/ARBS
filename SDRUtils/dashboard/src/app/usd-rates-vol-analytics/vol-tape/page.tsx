// ABOUTME: USD Rates Vol Analytics Vol Tape page.
import { Suspense } from "react";

import SwaptionTradeTape from "@/features/swaptions-tape/components/SwaptionTradeTape";

export default function VolTapePage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <SwaptionTradeTape />
    </Suspense>
  );
}
