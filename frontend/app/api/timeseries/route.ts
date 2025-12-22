import { NextResponse } from "next/server";

import { buildSeries } from "@/lib/sampleCatalog";
import { Frequency, TimeseriesRequest, TimeseriesResponse } from "@/lib/types";

function coerceFrequency(value: unknown): Frequency {
  return value === "W" || value === "M" ? value : "D";
}

export async function POST(request: Request): Promise<NextResponse<TimeseriesResponse>> {
  const payload = (await request.json()) as TimeseriesRequest;
  const { seriesIds, start, end, frequency } = payload;

  if (!seriesIds || !Array.isArray(seriesIds) || seriesIds.length === 0) {
    return NextResponse.json({ series: [] }, { status: 400 });
  }

  const startDate = new Date(start);
  const endDate = new Date(end);

  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return NextResponse.json({ series: [] }, { status: 400, statusText: "Invalid date range" });
  }

  const freq = coerceFrequency(frequency);
  const series = buildSeries(seriesIds, start, end, freq);

  return NextResponse.json({ series });
}
