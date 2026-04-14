import { useSidecarFetch } from './useSidecarFetch'
import type { TemporalCluster } from '../types'

export interface UseTemporalClustersParams {
  date: string
}

export function useTemporalClusters(params: UseTemporalClustersParams) {
  return useSidecarFetch<{ clusters: TemporalCluster[] }>('clusters', {
    date: params.date,
  })
}
