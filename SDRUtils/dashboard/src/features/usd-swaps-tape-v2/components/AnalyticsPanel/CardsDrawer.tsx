'use client'
// ABOUTME: Always-on collapsible drawer below the analytics-dock
// tabs that mounts the four PR-#286 cards (UnderlierMix,
// RfrAdoption, SwapSpreadVwap, CcpSwitch). Default collapsed; state
// persists to localStorage so the trader's preference survives
// reload. Visible in both single and sequence dock modes — the
// cards aggregate over the loaded row set and don't depend on the
// focused trade.
import type { JSX } from 'react'
import { useEffect, useState } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import { BlockHeatmapCard } from './BlockHeatmapCard'
import { CcpMarketShareCard } from './CcpMarketShareCard'
import { CcpSwitchCard } from './CcpSwitchCard'
import { CompressionCyclesCard } from './CompressionCyclesCard'
import { ForwardCalendarCard } from './ForwardCalendarCard'
import { IntradayVwapCard } from './IntradayVwapCard'
import { MaturityWallCard } from './MaturityWallCard'
import { NetNewRiskCard } from './NetNewRiskCard'
import { NovationVelocityCard } from './NovationVelocityCard'
import { PackageMixCard } from './PackageMixCard'
import { RfrAdoptionCard } from './RfrAdoptionCard'
import { SwapSpreadVwapCard } from './SwapSpreadVwapCard'
import { UnderlierMixCard } from './UnderlierMixCard'
import { VenueShiftCard } from './VenueShiftCard'

const STORAGE_KEY = 'cards-drawer-expanded'

export interface CardsDrawerProps {
  rows: readonly UsdSwapTapeRow[]
}

export function CardsDrawer({ rows }: CardsDrawerProps): JSX.Element {
  // Initial state mirrors the SSR-safe pattern used by AnalyticsPanel
  // for rarity prefs: server start at the default; useEffect rehydrates
  // from localStorage post-mount so SSR + CSR markup match.
  const [expanded, setExpanded] = useState<boolean>(() => {
    if (typeof localStorage === 'undefined') return false
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true'
    } catch {
      return false
    }
  })

  useEffect(() => {
    if (typeof localStorage === 'undefined') return
    try {
      localStorage.setItem(STORAGE_KEY, String(expanded))
    } catch {
      /* quota / private mode — fall back to in-memory */
    }
  }, [expanded])

  return (
    <div
      data-testid="cards-drawer"
      className="border-t border-slate-800 bg-slate-900/40"
    >
      <button
        type="button"
        className="w-full px-4 py-2 text-left font-mono text-[10.5px] uppercase tracking-wider text-slate-400 hover:bg-slate-800/50"
        aria-label={expanded ? 'Hide analytics cards' : 'Show analytics cards'}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? '▼ Hide analytics cards' : '▶ Show analytics cards'}
      </button>
      {expanded ? (
        <div className="grid max-h-[50vh] grid-cols-1 gap-4 overflow-y-auto p-4 lg:grid-cols-2">
          <div data-testid="underlier-mix-card">
            <UnderlierMixCard rows={rows} />
          </div>
          <div data-testid="rfr-adoption-card">
            <RfrAdoptionCard rows={rows} />
          </div>
          <div data-testid="swap-spread-vwap-card">
            <SwapSpreadVwapCard rows={rows} />
          </div>
          <div data-testid="ccp-switch-card">
            <CcpSwitchCard rows={rows} />
          </div>
          <div data-testid="net-new-risk-card">
            <NetNewRiskCard />
          </div>
          <div data-testid="block-heatmap-card">
            <BlockHeatmapCard />
          </div>
          <div data-testid="compression-cycles-card">
            <CompressionCyclesCard />
          </div>
          <div data-testid="package-mix-card">
            <PackageMixCard />
          </div>
          <div data-testid="ccp-market-share-card">
            <CcpMarketShareCard />
          </div>
          <div data-testid="forward-calendar-card">
            <ForwardCalendarCard />
          </div>
          <div data-testid="venue-shift-card">
            <VenueShiftCard />
          </div>
          <div data-testid="intraday-vwap-card">
            <IntradayVwapCard />
          </div>
          <div data-testid="novation-velocity-card">
            <NovationVelocityCard />
          </div>
          <div data-testid="maturity-wall-card">
            <MaturityWallCard />
          </div>
        </div>
      ) : null}
    </div>
  )
}
