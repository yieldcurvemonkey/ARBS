import { NextResponse } from 'next/server'

import type {
  UstsRvDataMode,
  UstsRvTimeseriesRequest,
  UstsRvValueColumn
} from '@/features/usts-rv/types'
import { getUstsRvTimeseries } from '@/lib/usts-rv/timeseries'

export const runtime = 'nodejs'

const VALUE_COLUMNS: UstsRvValueColumn[] = [
  'mmss',
  'ytm',
  'clean_price',
  'dirty_price',
  'mdur',
  'carry_bps',
  'roll_bps',
  'carry_and_roll_bps',
  'coupon'
]

const CUSIP_RE = /^[0-9A-Z]{9}$/
const CT_RE = /^CT\d{1,2}$/i
const DATA_MODES: UstsRvDataMode[] = ['eod_live', 'intraday_live']

function normalizeValueColumn(raw: unknown): UstsRvValueColumn {
  const txt = String(raw || '').trim()
  if (VALUE_COLUMNS.includes(txt as UstsRvValueColumn)) {
    return txt as UstsRvValueColumn
  }
  return 'ytm'
}

function normalizeCusips(raw: unknown): string[] {
  const normalizeToken = (item: unknown) => String(item || '').trim().toUpperCase()
  const isValidSeriesId = (item: string) => CUSIP_RE.test(item) || CT_RE.test(item)

  if (Array.isArray(raw)) {
    return raw
      .map(normalizeToken)
      .filter(isValidSeriesId)
  }

  if (typeof raw === 'string') {
    return raw
      .split(',')
      .map(normalizeToken)
      .filter(isValidSeriesId)
  }

  return []
}

function normalizeDataMode(raw: unknown): UstsRvDataMode | undefined {
  if (typeof raw !== 'string') return undefined
  return DATA_MODES.includes(raw as UstsRvDataMode)
    ? (raw as UstsRvDataMode)
    : undefined
}

function normalizeRequest(raw: any): UstsRvTimeseriesRequest {
  const req: UstsRvTimeseriesRequest = {
    valueColumn: normalizeValueColumn(raw?.valueColumn),
    cusips: normalizeCusips(raw?.cusips)
  }

  if (typeof raw?.asOf === 'string') req.asOf = raw.asOf
  if (typeof raw?.curveName === 'string') req.curveName = raw.curveName
  const dataMode = normalizeDataMode(raw?.dataMode)
  if (dataMode) req.dataMode = dataMode
  if (typeof raw?.startDate === 'string') req.startDate = raw.startDate
  if (typeof raw?.endDate === 'string') req.endDate = raw.endDate
  if (typeof raw?.startTime === 'string') req.startTime = raw.startTime
  if (typeof raw?.endTime === 'string') req.endTime = raw.endTime

  const lookbackDays = Number(raw?.lookbackDays)
  if (Number.isFinite(lookbackDays)) req.lookbackDays = Math.trunc(lookbackDays)

  return req
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const req = normalizeRequest({
    asOf: searchParams.get('asOf') ?? undefined,
    curveName: searchParams.get('curveName') ?? undefined,
    dataMode: searchParams.get('dataMode') ?? undefined,
    valueColumn: searchParams.get('valueColumn') ?? undefined,
    cusips: searchParams.get('cusips') ?? undefined,
    startDate: searchParams.get('startDate') ?? undefined,
    endDate: searchParams.get('endDate') ?? undefined,
    startTime: searchParams.get('startTime') ?? undefined,
    endTime: searchParams.get('endTime') ?? undefined,
    lookbackDays: searchParams.get('lookbackDays') ?? undefined
  })

  try {
    const data = await getUstsRvTimeseries(req)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('usts-rv/timeseries GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build UST RV timeseries' },
      { status: 500 }
    )
  }
}

export async function POST(request: Request) {
  let body: any = {}
  try {
    body = await request.json()
  } catch {
    body = {}
  }

  const req = normalizeRequest(body)

  try {
    const data = await getUstsRvTimeseries(req)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('usts-rv/timeseries POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build UST RV timeseries' },
      { status: 500 }
    )
  }
}
