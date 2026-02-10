import { NextResponse } from 'next/server'

import type {
  UstsRvSnapshotRequest,
  UstsRvValueColumn,
  UstsRvXColumn
} from '@/features/usts-rv/types'
import { getUstsRvSnapshot } from '@/lib/usts-rv/snapshot'

export const runtime = 'nodejs'

const VALUE_COLUMNS: UstsRvValueColumn[] = [
  'mmss',
  'ytm',
  'clean_price',
  'dirty_price',
  'mdur',
  'coupon'
]

const X_COLUMNS: UstsRvXColumn[] = ['ttm', 'mdur']

function normalizeValueColumns(raw: unknown): UstsRvValueColumn[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const values = raw
    .map((v) => String(v))
    .filter((v): v is UstsRvValueColumn =>
      VALUE_COLUMNS.includes(v as UstsRvValueColumn)
    )
  return values.length ? values : undefined
}

function normalizeXColumn(raw: unknown): UstsRvXColumn | undefined {
  if (typeof raw !== 'string') return undefined
  return X_COLUMNS.includes(raw as UstsRvXColumn)
    ? (raw as UstsRvXColumn)
    : undefined
}

function normalizeRequest(raw: any): UstsRvSnapshotRequest {
  const req: UstsRvSnapshotRequest = {}
  if (typeof raw?.asOf === 'string') req.asOf = raw.asOf
  if (typeof raw?.curveName === 'string') req.curveName = raw.curveName

  const xColumn = normalizeXColumn(raw?.xColumn)
  if (xColumn) req.xColumn = xColumn

  const minTtmNum = Number(raw?.minTtm)
  if (Number.isFinite(minTtmNum)) req.minTtm = minTtmNum

  const includeValues = normalizeValueColumns(raw?.includeValues)
  if (includeValues) req.includeValues = includeValues

  if (Array.isArray(raw?.splineConfigs)) {
    req.splineConfigs = raw.splineConfigs
      .filter((cfg: any) => cfg && typeof cfg === 'object')
      .map((cfg: any) => ({
        id: String(cfg.id ?? ''),
        enabled: cfg.enabled !== false,
        name: typeof cfg.name === 'string' ? cfg.name : undefined,
        method: cfg.method === 'loess' ? 'loess' : 'bspline',
        valueColumn: VALUE_COLUMNS.includes(cfg.valueColumn)
          ? cfg.valueColumn
          : 'mmss',
        xColumn: normalizeXColumn(cfg.xColumn),
        color: typeof cfg.color === 'string' ? cfg.color : undefined,
        lineWidth: Number.isFinite(Number(cfg.lineWidth))
          ? Number(cfg.lineWidth)
          : undefined,
        degree: Number.isFinite(Number(cfg.degree))
          ? Number(cfg.degree)
          : undefined,
        knots: Array.isArray(cfg.knots)
          ? cfg.knots
              .map((k: unknown) => Number(k))
              .filter((k: number) => Number.isFinite(k))
          : undefined,
        frac: Number.isFinite(Number(cfg.frac)) ? Number(cfg.frac) : undefined,
        it: Number.isFinite(Number(cfg.it)) ? Number(cfg.it) : undefined,
        delta: Number.isFinite(Number(cfg.delta)) ? Number(cfg.delta) : undefined,
        excludeRanks: Array.isArray(cfg.excludeRanks)
          ? cfg.excludeRanks
              .map((r: unknown) => Number(r))
              .filter((r: number) => Number.isFinite(r))
          : undefined,
        pointCount: Number.isFinite(Number(cfg.pointCount))
          ? Number(cfg.pointCount)
          : undefined,
        xMin:
          cfg.xMin === null
            ? null
            : Number.isFinite(Number(cfg.xMin))
              ? Number(cfg.xMin)
              : undefined,
        xMax:
          cfg.xMax === null
            ? null
            : Number.isFinite(Number(cfg.xMax))
              ? Number(cfg.xMax)
              : undefined
      }))
      .filter((cfg: { id: string }) => Boolean(cfg.id))
  }

  return req
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const includeValuesRaw = searchParams.get('includeValues')
  const includeValues = includeValuesRaw
    ? includeValuesRaw.split(',').map((v) => v.trim())
    : undefined

  const req = normalizeRequest({
    asOf: searchParams.get('asOf') ?? undefined,
    curveName: searchParams.get('curveName') ?? undefined,
    xColumn: searchParams.get('xColumn') ?? undefined,
    minTtm: searchParams.get('minTtm') ?? undefined,
    includeValues
  })

  try {
    const data = await getUstsRvSnapshot(req)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('usts-rv/snapshot GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build UST RV snapshot' },
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
    const data = await getUstsRvSnapshot(req)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('usts-rv/snapshot POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build UST RV snapshot' },
      { status: 500 }
    )
  }
}
