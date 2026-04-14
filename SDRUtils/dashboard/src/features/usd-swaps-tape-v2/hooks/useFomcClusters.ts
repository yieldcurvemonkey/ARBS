import { useSidecarFetch } from './useSidecarFetch'
import type { FomcMeeting } from '../types'

export interface UseFomcClustersParams {
  date: string
}

export function useFomcClusters(params: UseFomcClustersParams) {
  return useSidecarFetch<{ meetings: FomcMeeting[] }>('fomc-clusters', {
    date: params.date,
  })
}
