export type StirTapeRow = {
  package_id: string
  package_type: string | null
  curve_id: string | null
  policy_central_bank: string | null
  cb_dated_confidence: number | null
  execution_start: string
  execution_end: string | null
  effective_date: string | null
  expiration_date: string | null
  legs_count: number | null
  total_notional: number | null
  gross_notional: number | null
  total_risk: number | null
  gross_risk: number | null
  package_metrics: unknown
  legs_json: unknown
}

export type StirCentralBankSummary = {
  centralBank: string
  packageCount: number
  grossNotional: number
  grossRisk: number
}

export type StirSummary = {
  totalPackages: number
  totalNotional: number
  totalRisk: number
  unmappedCount: number
  byCentralBank: StirCentralBankSummary[]
}

export type StirFlowHistoryDay = {
  date: string
  byCentralBank: StirCentralBankSummary[]
}

export type StirMeetingLadderRow = {
  centralBank: string
  startMeeting: string
  endMeeting: string
  tradeCount: number
  grossNotional: number
  grossRisk: number
}

export type StirCurveGridNode = {
  nodeDate: string
  zeroRate: number | null
  prevZeroRate: number | null
  discountFactor: number | null
}

export type StirCurveGridCurve = {
  curveName: string
  referenceKey: string
  currency: string
  centralBank: string | null
  snapshotTs: string
  nodes: StirCurveGridNode[]
}

export type StirPackageBreakdownRow = {
  packageType: string
  packageCount: number
  grossNotional: number
  grossRisk: number
}

export type StirAliasRateRow = {
  alias: string
  meetingLabel: string | null
  requestedCentralBank: string | null
  centralBank: string | null
  curveKey: string | null
  startMeeting: string | null
  endMeeting: string | null
  lastExecutionTimestamp: string | null
  lastFixedRate: number | null
  avgFixedRate: number | null
  tradeCount: number
}

export type StirAliasTimeseriesPoint = {
  bucketTs: string
  tradeCount: number
  avgFixedRate: number | null
  lastFixedRate: number | null
}

export type StirOvernightForwardCurvePoint = {
  nodeDate: string
  zeroRate: number | null
  discountFactor: number | null
  forwardRate: number | null
}

export type StirOvernightForwardCurveSeries = {
  curveName: string
  referenceKey: string
  currency: string
  centralBank: string | null
  snapshotTs: string
  points: StirOvernightForwardCurvePoint[]
}
