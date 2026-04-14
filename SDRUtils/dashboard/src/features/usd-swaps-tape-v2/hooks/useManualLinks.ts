// Manual-link client wrapper hitting /api/usd-swaps-tape-v2/links.
import { useCallback, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'

type LinkResponse = { link_id: string; manual_package_id: string }

export interface UseManualLinksReturn {
  creating: boolean
  error: string | null
  createLink: (body: {
    manual_package_id: string
    package_type: string
    linked_trade_ids: string[]
    created_by: string
    user_comment?: string
    link_reason?: string
    tags?: string[]
  }) => Promise<LinkResponse | null>
  updateLink: (
    linkId: string,
    patch: Partial<{ user_comment: string; link_reason: string; tags: string[] }>,
  ) => Promise<LinkResponse | null>
  deleteLink: (linkId: string) => Promise<boolean>
}

export function useManualLinks(): UseManualLinksReturn {
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createLink: UseManualLinksReturn['createLink'] = useCallback(async (body) => {
    setCreating(true)
    setError(null)
    try {
      const res = await fetch(`${TAPE_V2_API_BASE}/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`createLink failed: ${res.statusText}`)
      return (await res.json()) as LinkResponse
    } catch (e) {
      setError(e instanceof Error ? e.message : 'create failed')
      return null
    } finally {
      setCreating(false)
    }
  }, [])

  const updateLink: UseManualLinksReturn['updateLink'] = useCallback(
    async (linkId, patch) => {
      try {
        const res = await fetch(`${TAPE_V2_API_BASE}/links/${linkId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        })
        if (!res.ok) throw new Error(`updateLink failed: ${res.statusText}`)
        return (await res.json()) as LinkResponse
      } catch (e) {
        setError(e instanceof Error ? e.message : 'update failed')
        return null
      }
    },
    [],
  )

  const deleteLink = useCallback(async (linkId: string) => {
    try {
      const res = await fetch(`${TAPE_V2_API_BASE}/links/${linkId}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`deleteLink failed: ${res.statusText}`)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'delete failed')
      return false
    }
  }, [])

  return { creating, error, createLink, updateLink, deleteLink }
}
