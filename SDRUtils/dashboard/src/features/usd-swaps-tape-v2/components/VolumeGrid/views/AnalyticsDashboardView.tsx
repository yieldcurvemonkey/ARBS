'use client'
import type { JSX } from 'react'
import type { ViewProps } from '../../../types/volume-grid-views.types'
import { BlockHeatmapCard } from '../../AnalyticsPanel/BlockHeatmapCard'
import { CcpMarketShareCard } from '../../AnalyticsPanel/CcpMarketShareCard'
import { CompressionCyclesCard } from '../../AnalyticsPanel/CompressionCyclesCard'
import { DealerLadderPanel } from '../../AnalyticsPanel/DealerLadderPanel'
import { ForwardCalendarCard } from '../../AnalyticsPanel/ForwardCalendarCard'
import { MaturityWallCard } from '../../AnalyticsPanel/MaturityWallCard'
import { NetNewRiskCard } from '../../AnalyticsPanel/NetNewRiskCard'
import { NovationVelocityCard } from '../../AnalyticsPanel/NovationVelocityCard'
import { PackageMixCard } from '../../AnalyticsPanel/PackageMixCard'
import { VenueShiftCard } from '../../AnalyticsPanel/VenueShiftCard'

export function AnalyticsDashboardView(_props: ViewProps): JSX.Element {
  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
      {/* Full width: the ladder is a two-pane view (cross-bucket z beside one
          bucket's own history) and does not fit a third of a row. */}
      <div className="md:col-span-2 xl:col-span-3">
        <DealerLadderPanel />
      </div>
      <NetNewRiskCard />
      <BlockHeatmapCard />
      <PackageMixCard />
      <CcpMarketShareCard />
      <NovationVelocityCard />
      <CompressionCyclesCard />
      <VenueShiftCard />
      <ForwardCalendarCard />
      <MaturityWallCard />
    </div>
  )
}
