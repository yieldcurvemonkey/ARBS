// ABOUTME: Root page renders the Swaption trade tape directly.
import { Suspense } from "react";
import SwaptionTradeTape from "@/features/swaptions-tape/components/SwaptionTradeTape";

export default function HomePage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <SwaptionTradeTape />
    </Suspense>
  );
}
