/**
 * Hook for managing manual trade links state
 * Frontend-driven: all computation happens here
 */

import { useState, useCallback, useEffect } from 'react'

export type ManualLink = {
  link_id: string
  linked_trade_ids: string[]
  created_by: string
  created_at: string
  updated_at: string | null
  user_comment: string | null
  tags: string[]
  is_active: boolean
}

type CreateLinkParams = {
  trade_ids: string[]
  comment?: string
  tags?: string[]
  user: string
}

type UpdateLinkParams = {
  link_id: string
  comment?: string
  tags?: string[]
}

export function useManualLinks() {
  const [links, setLinks] = useState<ManualLink[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load links for a date range
  const loadLinks = useCallback(async (start?: string, end?: string) => {
    setIsLoading(true)
    setError(null)

    try {
      const params = new URLSearchParams()
      if (start) params.set('start', start)
      if (end) params.set('end', end)

      const response = await fetch(`/api/manual-links?${params}`)
      if (!response.ok) {
        throw new Error(`Failed to load links: ${response.statusText}`)
      }

      const data = await response.json()
      setLinks(data.links || [])
    } catch (err: any) {
      setError(err.message)
      console.error('Failed to load manual links:', err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Create a new link
  const createLink = useCallback(async (params: CreateLinkParams): Promise<ManualLink | null> => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch('/api/manual-links', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Failed to create link')
      }

      const data = await response.json()
      const newLink = data.link

      // Update local state
      setLinks(prev => [newLink, ...prev])

      return newLink
    } catch (err: any) {
      setError(err.message)
      console.error('Failed to create manual link:', err)
      return null
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Update an existing link
  const updateLink = useCallback(async (params: UpdateLinkParams): Promise<boolean> => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/manual-links/${params.link_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          comment: params.comment,
          tags: params.tags
        })
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Failed to update link')
      }

      const data = await response.json()
      const updatedLink = data.link

      // Update local state
      setLinks(prev =>
        prev.map(link =>
          link.link_id === updatedLink.link_id ? updatedLink : link
        )
      )

      return true
    } catch (err: any) {
      setError(err.message)
      console.error('Failed to update manual link:', err)
      return false
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Delete a link (soft delete)
  const deleteLink = useCallback(async (linkId: string): Promise<boolean> => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/manual-links?link_id=${linkId}`, {
        method: 'DELETE'
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Failed to delete link')
      }

      // Remove from local state
      setLinks(prev => prev.filter(link => link.link_id !== linkId))

      return true
    } catch (err: any) {
      setError(err.message)
      console.error('Failed to delete manual link:', err)
      return false
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Get links for specific trade IDs
  const getLinksForTrades = useCallback((tradeIds: string[]): ManualLink[] => {
    return links.filter(link =>
      link.linked_trade_ids.some(id => tradeIds.includes(id))
    )
  }, [links])

  // Check if a trade is linked
  const isTradeLinked = useCallback((tradeId: string): boolean => {
    return links.some(link =>
      link.linked_trade_ids.includes(tradeId)
    )
  }, [links])

  // Get all linked trade IDs
  const linkedTradeIds = useCallback((): Set<string> => {
    const ids = new Set<string>()
    links.forEach(link => {
      link.linked_trade_ids.forEach(id => ids.add(id))
    })
    return ids
  }, [links])

  return {
    links,
    isLoading,
    error,
    loadLinks,
    createLink,
    updateLink,
    deleteLink,
    getLinksForTrades,
    isTradeLinked,
    linkedTradeIds
  }
}
