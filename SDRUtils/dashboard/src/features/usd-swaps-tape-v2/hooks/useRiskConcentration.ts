import { useSidecarFetch } from './useSidecarFetch'
import type { RiskConcentrationGroup } from '../types'

export interface UseRiskConcentrationParams {
  date: string
  groupBy:
    | 'tape_label'
    | 'trade_type'
    | 'venue'
    | 'ccp'
    | 'session'
    | 'tenor'
    | 'rate_index'
    | 'fomc_meeting'
  clean?: boolean
}

export function useRiskConcentration(params: UseRiskConcentrationParams) {
  return useSidecarFetch<{ groups: RiskConcentrationGroup[] }>(
    'risk-concentration',
    {
      date: params.date,
      groupBy: params.groupBy,
      clean: params.clean ? 'true' : undefined,
    },
  )
}
