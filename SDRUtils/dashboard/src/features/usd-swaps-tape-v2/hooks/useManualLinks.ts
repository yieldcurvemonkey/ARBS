// ABOUTME: Manual-link hook surface for v2. Delegates to the shared
// useManualLinkForm + manualLinkApi from lib/manual-links-ui. The legacy
// minimal CRUD interface (createLink / updateLink / deleteLink) is
// preserved as a compatibility shim so existing call sites don't need
// to change in this commit; later phases (Phase E.2 / E.3) replace
// those call sites with the shared form / detail-modal surface.

import { useCallback, useMemo, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import {
  createManualLinkApi,
  type CreateLinkBody,
  type ManualLinkApiClient,
} from '@/lib/manual-links-ui/api/manualLinkApi'

const V2_LINKS_BASE = `${TAPE_V2_API_BASE}/links`

type LegacyCreatePayload = {
  manual_package_id: string
  package_type: string
  linked_trade_ids: string[]
  created_by: string
  user_comment?: string
  link_reason?: string
  tags?: string[]
}

type LinkResponse = { link_id: string; manual_package_id: string }

export interface UseManualLinksReturn {
  creating: boolean
  error: string | null
  createLink: (body: LegacyCreatePayload) => Promise<LinkResponse | null>
  updateLink: (
    linkId: string,
    patch: Partial<{ user_comment: string; link_reason: string; tags: string[] }>,
    adminPassword?: string,
  ) => Promise<LinkResponse | null>
  deleteLink: (linkId: string, adminPassword?: string) => Promise<boolean>
  /** Direct handle on the typed client (for new call sites). */
  api: ManualLinkApiClient
}

export function useManualLinks(): UseManualLinksReturn {
  const api = useMemo(() => createManualLinkApi(V2_LINKS_BASE), [])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createLink = useCallback<UseManualLinksReturn['createLink']>(
    async (body) => {
      setCreating(true)
      setError(null)
      try {
        const payload: CreateLinkBody = {
          trade_ids: body.linked_trade_ids,
          created_by: body.created_by,
          user: body.created_by,
          package_type: body.package_type,
          link_reason: body.link_reason,
          user_comment: body.user_comment,
          tags: body.tags,
          manual_package_id: body.manual_package_id,
        }
        return await api.createLink(payload)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'create failed')
        return null
      } finally {
        setCreating(false)
      }
    },
    [api],
  )

  const updateLink = useCallback<UseManualLinksReturn['updateLink']>(
    async (linkId, patch, adminPassword = '') => {
      try {
        return await api.updateLink(linkId, patch, adminPassword)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'update failed')
        return null
      }
    },
    [api],
  )

  const deleteLink = useCallback<UseManualLinksReturn['deleteLink']>(
    async (linkId, adminPassword = '') => {
      try {
        await api.deactivateLink(linkId, adminPassword)
        return true
      } catch (e) {
        setError(e instanceof Error ? e.message : 'delete failed')
        return false
      }
    },
    [api],
  )

  return { creating, error, createLink, updateLink, deleteLink, api }
}
