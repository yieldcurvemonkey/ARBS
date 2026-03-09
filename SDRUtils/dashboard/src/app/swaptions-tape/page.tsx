// ABOUTME: Legacy swaptions-tape route retained as a redirect to the nested Vol Tape page.
import { redirect } from "next/navigation";

export default function SwaptionsTapePage() {
  redirect("/usd-rates-vol-analytics/vol-tape");
}
