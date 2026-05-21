import type { VolumeGridViewDef } from '../../../types/volume-grid-views.types'
import { DefaultGridView } from './DefaultGridView'
import { FomcStripView } from './FomcStripView'
import { CurveStripView } from './CurveStripView'
import { FlyCurveView } from './FlyCurveView'
import { CustomGridView } from './CustomGridView'

export const VOLUME_GRID_VIEWS: ReadonlyArray<VolumeGridViewDef> = [
  {
    id: 'default',
    label: 'Grid',
    component: DefaultGridView,
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
    label: 'Fly Curve',
    component: FlyCurveView,
    controls: () => null,
  },
  {
    id: 'custom',
    label: 'Custom',
    component: CustomGridView,
    controls: () => null,
  },
]
