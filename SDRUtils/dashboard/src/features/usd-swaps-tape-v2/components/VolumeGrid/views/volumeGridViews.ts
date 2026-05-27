import type { VolumeGridViewDef } from '../../../types/volume-grid-views.types'
import { DefaultGridView } from './DefaultGridView'
import { FomcStripView } from './FomcStripView'
import { CurveStripView } from './CurveStripView'
import { FlyCurveView } from './FlyCurveView'
import { SpreadoverStripView } from './SpreadoverStripView'
import { InvoiceStripView } from './InvoiceStripView'
import { CustomGridView } from './CustomGridView'
import { MarketOverviewView } from './MarketOverviewView'

export const VOLUME_GRID_VIEWS: ReadonlyArray<VolumeGridViewDef> = [
  {
    id: 'default',
    label: 'Grid',
    component: DefaultGridView,
    controls: () => null,
  },
  {
    id: 'market_overview',
    label: 'Market Overview',
    component: MarketOverviewView,
    controls: () => null,
  },
  {
    id: 'fomc_strip',
    label: 'FOMC Strip',
    component: FomcStripView,
    controls: () => null,
  },
  {
    id: 'curve_strip',
    label: 'Curve Strip',
    component: CurveStripView,
    controls: () => null,
  },
  {
    id: 'fly_curve',
    label: 'Fly Strip',
    component: FlyCurveView,
    controls: () => null,
  },
  {
    id: 'spreadover_strip',
    label: 'Spreadover Strip',
    component: SpreadoverStripView,
    controls: () => null,
  },
  {
    id: 'invoice_strip',
    label: 'Invoice Strip',
    component: InvoiceStripView,
    controls: () => null,
  },
  {
    id: 'custom',
    label: 'Custom',
    component: CustomGridView,
    controls: () => null,
  },
]
