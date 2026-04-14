import { useSidecarFetch } from './useSidecarFetch'
import type { PackageSummary } from '../types'

export interface UsePackageBrowserParams {
  date: string
  sortBy?: 'risk' | 'notional' | 'time' | 'legs'
  limit?: number
}

export function usePackageBrowser(params: UsePackageBrowserParams) {
  return useSidecarFetch<{ packages: PackageSummary[] }>('packages', {
    date: params.date,
    sortBy: params.sortBy ?? 'risk',
    limit: params.limit ?? 100,
  })
}
