/**
 * Badge component showing manual link indicator for trades
 */

'use client'

import { Badge } from 'primereact/badge'
import { Tooltip } from 'primereact/tooltip'
import type { ManualLink } from '@/hooks/useManualLinks'

type Props = {
  tradeId: string
  links: ManualLink[]
  onClick?: (link: ManualLink) => void
}

export function ManualLinkBadge({ tradeId, links, onClick }: Props) {
  // Find links containing this trade
  const relevantLinks = links.filter(link =>
    link.linked_trade_ids.includes(tradeId)
  )

  if (relevantLinks.length === 0) {
    return null
  }

  const primaryLink = relevantLinks[0]
  const tooltipId = `link-badge-${tradeId}`

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const tooltipContent = (
    <div className="space-y-2 max-w-xs">
      <div className="font-semibold text-sm">
        {relevantLinks.length} Manual Link{relevantLinks.length > 1 ? 's' : ''}
      </div>
      {relevantLinks.map((link, idx) => (
        <div key={link.link_id} className="border-t border-gray-600 pt-2 text-xs">
          <div className="text-gray-300">
            Linked with {link.linked_trade_ids.length - 1} other trade
            {link.linked_trade_ids.length - 1 !== 1 ? 's' : ''}
          </div>
          {link.user_comment && (
            <div className="mt-1 text-gray-400 italic">
              "{link.user_comment.slice(0, 100)}
              {link.user_comment.length > 100 ? '...' : ''}"
            </div>
          )}
          {link.tags && link.tags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {link.tags.map((tag: string) => (
                <span
                  key={tag}
                  className="px-1.5 py-0.5 bg-blue-900/50 text-blue-200 rounded text-xs"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
          <div className="mt-1 text-gray-500 text-xs">
            By {link.created_by} • {formatDate(link.created_at)}
          </div>
        </div>
      ))}
      <div className="text-gray-500 text-xs mt-2 border-t border-gray-600 pt-2">
        Click to view details
      </div>
    </div>
  )

  return (
    <>
      <Tooltip target={`.${tooltipId}`} position="right" mouseTrack>
        {tooltipContent}
      </Tooltip>
      <button
        className={`${tooltipId} inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-blue-600/80 hover:bg-blue-600 transition-colors cursor-pointer`}
        onClick={(e) => {
          e.stopPropagation()
          if (onClick) onClick(primaryLink)
        }}
      >
        <i className="pi pi-link text-xs"></i>
        {relevantLinks.length > 1 && (
          <span className="font-semibold">{relevantLinks.length}</span>
        )}
      </button>
    </>
  )
}
