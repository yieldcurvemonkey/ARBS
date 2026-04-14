export type RiskConcentrationGroup = {
  value: string
  trade_count: number
  total_dv01: number
  total_notional: number
}

export type PackageSummary = {
  package_id: string
  package_structure: string | null
  package_type: string | null
  n_package_legs: number | null
  legs_count: number
  total_risk: number | null
  total_notional: number | null
  rate_index_clean: string | null
  venue: string | null
  ccp: string | null
  tape_label: string | null
  execution_start: string
  cluster_id: string | null
}

export type FomcMeeting = {
  fomc_meeting_label: string
  meeting_date: string | null
  trade_count: number
  net_risk: number
  gross_notional: number
  has_multi_meeting_flow: boolean
}

export type TemporalCluster = {
  cluster_id: string
  start_ts: string
  end_ts: string
  trade_count: number
  total_risk: number
  gross_notional: number
  tape_labels: string[]
  lifecycle_types: string[]
}
