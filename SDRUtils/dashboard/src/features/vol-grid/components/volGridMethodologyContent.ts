export type MethodologySection = {
  id: string
  label: string
  markdown: string
}

export const VOL_GRID_METHODOLOGY_TITLE = 'Live ATMF Vol Grid Methodology'

export const VOL_GRID_METHODOLOGY_SECTIONS: MethodologySection[] = [
  {
    id: 'overview',
    label: 'Overview',
    markdown: String.raw`
# Live ATMF Vol Grid Methodology

This modal documents the implemented methodology behind the live ATMF swaption vol grid so a quant/dev team can reproduce it from raw stored surfaces and package rows, not just use the UI as a black box.

## Primary implementation sources

- \`SDRUtils/_swappulse_scripts/ingest_and_build_live_atmf_grid.py\`
  - intraday snapshot build
  - observation extraction / inference
  - node mapping / anchor propagation
  - premium generation
- \`RVUtils/surface_pca_model.py\`
  - EOD PCA fit on daily surface changes
  - conditional multivariate-normal update
- \`SDRUtils/dashboard/src/features/vol-grid/components/VolGridDashboard.tsx\`
  - polling / header state / view selection
- \`SDRUtils/dashboard/src/lib/vol-grid/engine.ts\`
  - snapshot read path
  - display-grid interpolation and metadata transforms
- \`SDRUtils/dashboard/src/lib/vol-grid/session.ts\`
  - live vs closing-view session selection

## Stored artifacts

| Table | Purpose |
|---|---|
| \`arbs_atmf_grid_eod_history_v1\` | Stored EOD core-grid histories |
| \`arbs_atmf_grid_pca_models_v1\` | Serialized PCA model (mean, loadings, eigenvalues, variances) |
| \`arbs_live_atmf_grid_snapshots_v1\` | Intraday / close snapshots plus node metadata |
| \`arbs_live_atmf_grid_observations_v1\` | Per-trade mapped observations written alongside snapshots |
| \`arbs_swaption_manual_straddles_v1\` | Optional manual incomplete-straddle overrides |

## End-to-end build order

1. Ensure a continuous EOD history window exists for the core surface.
2. Fit or reuse a PCA model on daily changes of the EOD core grid.
3. Pull same-day package rows from \`arbs_swaption_packages_v1\` and leg detail from \`arbs_swaption_legs_v1\`.
4. Convert qualifying straddles and selected ATM IDB outrights into \`StraddleObservation\` objects.
5. Filter observations by preset, action allowlist, valid coordinates, and intraday staleness.
6. Map each observation onto the core grid, preferably with bilinear weights in log-expiry/log-tenor space.
7. Apply an MVN conditional update from the EOD base surface.
8. Hard-anchor near-exact observations, then propagate anchor residuals across the core grid.
9. Reprice ATMF forward straddle premiums off the resulting live grid.
10. Store the snapshot and expose it through the dashboard read path.
11. Interpolate core outputs onto the extended display grid used by the UI.

## Default constants in code

| Constant | Value | Meaning |
|---|---:|---|
| \`DEFAULT_COMPONENTS\` | 5 | PCA factors retained |
| \`DEFAULT_LOOKBACK_BUSINESS_DAYS\` | 520 | EOD history window for fitting |
| \`DEFAULT_HALF_LIFE_MINUTES\` | 120 | Observation staleness half-life |
| \`DEFAULT_MAX_STALENESS_MINUTES\` | 480 | Intraday observation cutoff |
| \`DEFAULT_BASE_NOISE_BPVOL\` | 0.5 | Base observation noise scale |
| \`DEFAULT_TENOR_WEIGHT\` | 0.7 | Relative weight of tenor in log-distance |
| \`DIRECT_OBSERVATION_ANCHOR_MIN_WEIGHT\` | 0.95 | Threshold to treat an observation as a direct node anchor |
| \`DIRECT_ANCHOR_PROPAGATION_LENGTH_SCALE\` | 0.7 | Exponential kernel decay for residual propagation |
| \`DIRECT_ANCHOR_PROPAGATION_PRIOR_WEIGHT\` | 1.0 | Stabilizer in propagated residual denominator |
| \`DEFAULT_PREMIUM_NOTIONAL\` | 100,000,000 | Notional used when computing ATMF premiums |
`,
  },
  {
    id: 'surface-grid',
    label: 'Surface Grid',
    markdown: String.raw`
# Core Surface, Display Surface, and Missing-Node Completion

## Core calibration grid

The PCA model and stored live snapshots are calibrated on the core node set:

- expiries: \`1m, 3m, 6m, 1y, 2y, 3y, 5y, 7y, 10y, 15y, 20y\`
- tenors: \`1y, 2y, 5y, 10y, 20y, 30y\`

So the modeled state vector has:

$$
N = 11 \times 6 = 66
$$

ordered columns, with ordering inherited from \`SURFACE_NODE_KEYS\`.

## Extended display grid

The dashboard shows a wider tenor axis:

- display tenors: \`1y, 2y, 3y, 5y, 7y, 10y, 20y, 30y\`

So the UI displays an 11 x 8 grid. The 3Y and 7Y tenor columns are not independently calibrated state variables; they are interpolated from the surrounding core-grid nodes on read.

## Label-to-years conversion

All tenor/expiry labels are converted to year fractions by:

$$
\text{years}(xD) = \frac{x}{365}, \qquad
\text{years}(xW) = \frac{x}{52}, \qquad
\text{years}(xM) = \frac{x}{12}, \qquad
\text{years}(xY) = x
$$

## Filling missing raw EOD core nodes

When an EOD surface arrives with missing core nodes, the script fills the core matrix in log-space using \`scipy.interpolate.griddata\`:

1. cubic interpolation
2. fallback to linear where cubic is \`NaN\`
3. fallback to nearest-neighbor at uncovered boundaries

The interpolation domain is:

$$
(\log(\text{expiry years}),\ \log(\text{tenor years}))
$$

That means the backfill logic assumes a smoother surface in multiplicative time coordinates than in raw linear years.

## Consequence for reverse engineering

- The stored PCA model is always fit on the 66-node core grid.
- Display-only tenors are a presentation-layer interpolation, not an independently estimated state.
- If you want byte-for-byte parity with the UI, reproduce the core snapshot first, then run the dashboard interpolation logic afterward.
`,
  },
  {
    id: 'observations',
    label: 'Observations',
    markdown: String.raw`
# Observation Extraction and Incomplete-Straddle Inference

## Raw source query

Same-day candidate packages are pulled from:

- \`arbs_swaption_packages_v1\`
- \`arbs_swaption_legs_v1\`

The selection date is ET-local:

~~~sql
WHERE (p.execution_start AT TIME ZONE 'America/New_York')::date = :as_of_date
  AND upper(replace(coalesce(p.package_type, ''), '-', '_')) IN ('STRADDLE', 'OUTRIGHT')
~~~

Leg metadata is aggregated into \`legs_json\`, and modal platform / action are rolled up via \`mode()\`.

## What becomes an observation

An observation is emitted only if one of the following is true:

1. the package is already a \`STRADDLE\`
2. the row is manually flagged in \`arbs_swaption_manual_straddles_v1\`
3. the row is an IDB ATM outright that the heuristic upgrades into an incomplete straddle

The stored observation payload includes:

- execution timestamp
- forward / tenor labels and year counts
- observed bpvol
- premium
- notional
- platform identifier and derived platform type
- source package type
- flags for manual or inferred incomplete straddles

## Straddle bpvol extraction

For actual straddles the script tries, in order:

1. \`package_metrics.straddle_bpvol_yr\`
2. first-leg \`leg_metrics.straddle_bpvol_yr\`

For inferred incomplete straddles it falls back to the outright single-leg metric:

$$
\text{observed straddle bpvol} = 0.5 \times \text{outright bpvol}
$$

using \`STRADDLE_SPLIT_FACTOR = 0.5\`.

## Straddle premium extraction

If leg premiums exist, each leg premium is halved and summed:

$$
P_{\text{straddle}} = \sum_{\ell \in \text{legs}} 0.5 \cdot P_{\ell}
$$

Otherwise the code falls back to \`total_premium\`.

## Incomplete-straddle heuristic

The inference path is intentionally explicit and narrow. A candidate outright must satisfy all of:

- package type is \`OUTRIGHT\`
- not manual / hybrid
- platform classifies as IDB
- exactly one leg
- leg appears ATM / ATMF
- leg text matches \`EURO VANILLA PHYS\`
- leg direction is identifiable as payer or receiver
- there is not already a complete payer+receiver signature for the same structure

The duplicate-prevention signature is:

$$
\text{signature} =
(\text{trade date},\ \text{option expiry date},\ \text{underlier maturity date},\ \text{forward} \times \text{tenor},\ \text{rounded notional bucket})
$$

where the notional bucket is rounded in millions.

## Ratio trigger against real straddles

For the same forward x tenor series, the heuristic compares outright bpvol against:

- the most recent actual straddle bpvol
- a median baseline of actual straddle bpvol samples

The outright is upgraded only if:

$$
1.45 \le
\frac{\text{outright bpvol}}{\text{reference straddle bpvol}}
\le 2.95
$$

## Fallback trigger when no reliable same-series reference exists

If the outright ratio test cannot be satisfied, the code uses a forward-dependent absolute bpvol threshold:

$$
\text{threshold}(f) =
\begin{cases}
130,& f \le 0.5 \\
125,& 0.5 < f \le 1 \\
120,& 1 < f \le 2 \\
112,& 2 < f \le 5 \\
100,& 5 < f \le 10 \\
90,& f > 10
\end{cases}
$$

If:

$$
\text{outright bpvol} \ge \text{threshold}(f)
$$

the row is flagged as an incomplete straddle.

## Preset filtering after extraction

After raw observation construction, the snapshot builder applies a narrower preset filter:

- platform type must match preset
- \`event_action\` must start with \`NEWT\`, \`MODI\`, or \`CORR\`
- forward and tenor coordinates must exist
- for intraday snapshots only, age must be <= \`max_staleness_minutes\`

No other dynamic UI-side config filters are applied during snapshot retrieval.
`,
  },
  {
    id: 'mapping',
    label: 'Grid Mapping',
    markdown: String.raw`
# Mapping Trades onto the Grid

## Distance metric

Nearest-node logic operates in log-expiry/log-tenor space with a tenor penalty:

$$
d((f, t), n) =
\sqrt{
\left( \log f - \log f_n \right)^2 +
\left( w_t \cdot (\log t - \log t_n) \right)^2
}
$$

where:

- \(f\) = forward years
- \(t\) = tenor years
- \(w_t\) = \`tenor_weight\` (default 0.7)

This is used for:

- core-node nearest mapping
- display-node nearest mapping
- direct-anchor propagation distance

## Display-node mapping

Every observation always receives a nearest display node on the extended 11 x 8 grid. This is purely for UI attribution.

## Core-node mapping: continuous path

The preferred path is not pure nearest-node. The script builds bilinear weights against the surrounding rectangle of core nodes in log-space.

Let \(f_{lo}, f_{hi}\) be the bracketing expiry years and \(t_{lo}, t_{hi}\) the bracketing tenor years. Then:

$$
s =
\frac{\log f - \log f_{lo}}
{\log f_{hi} - \log f_{lo}},
\qquad
r =
\frac{\log t - \log t_{lo}}
{\log t_{hi} - \log t_{lo}}
$$

clamped into \([0, 1]\).

The four corner weights are:

$$
w_{lo,lo} = (1-s)(1-r)
$$

$$
w_{lo,hi} = (1-s)r
$$

$$
w_{hi,lo} = s(1-r)
$$

$$
w_{hi,hi} = sr
$$

with only positive weights retained. The row of the observation operator therefore has between 1 and 4 non-zero entries summing to 1.

## Backward-compatible primary node

Even in the continuous path, the code still stores:

- \`core_node_key\` = highest-weight corner's nearest core node
- \`mapping_distance\` = nearest-core log distance

That is a metadata convenience layer. The actual Bayesian update uses the full bilinear row in \(H\), not just the single nearest node.

## Legacy fallback path

If continuous weights are unavailable, observations collapse to a single nearest core node before the update. That path is still supported but is not the intended calibration mode anymore.
`,
  },
  {
    id: 'pca',
    label: 'PCA Prior',
    markdown: String.raw`
# PCA Prior on Daily Surface Changes

## Training matrix

Let \(L_t \in \mathbb{R}^{66}\) be the EOD core-grid level vector on date \(t\), ordered by \`SURFACE_NODE_KEYS\`.

The PCA fit is run on first differences:

$$
X_t = L_t - L_{t-1}
$$

not on raw levels.

## Mean and covariance

The code computes:

$$
\mu = \frac{1}{T} \sum_{t=1}^{T} X_t
$$

and then centers:

$$
\tilde{X}_t = X_t - \mu
$$

The sample covariance is:

$$
\Sigma =
\frac{1}{T-1}
\tilde{X}^{\top}\tilde{X}
$$

## Eigendecomposition

The PCA model is built from:

$$
\Sigma = V \Lambda V^{\top}
$$

with eigenpairs sorted descending by eigenvalue and the top \(k\) retained, where:

$$
k = \min(\max(\text{n\_components}, 1), 66)
$$

and the default is \(k=5\).

The stored model fields are:

- \`mean\` = \(\mu\)
- \`loadings\` = \(V_k\)
- \`eigenvalues\` = diagonal entries of \(\Lambda_k\)
- \`total_variance\` = \(\operatorname{diag}(\Sigma)\)
- \`residual_variance\` = unexplained nodewise variance

## Residual variance

For node \(j\), the explained variance under the retained PCA factors is:

$$
\text{explained}_j =
\sum_{m=1}^{k}
V_{j,m}^2 \lambda_m
$$

and the residual variance stored in the model is:

$$
D_j =
\max(\Sigma_{j,j} - \text{explained}_j,\ 0)
$$

So the prior decomposition used later is:

$$
\Delta L = \mu + V_k f + \varepsilon
$$

with:

$$
f \sim \mathcal{N}(0, \Lambda_k),
\qquad
\varepsilon \sim \mathcal{N}(0, \operatorname{diag}(D))
$$

## Training window

The build script typically requests 520 business days of EOD history up to the anchor EOD date, refetching any missing dates and reusing a stored model if it already covers the anchor date.
`,
  },
  {
    id: 'bayesian-update',
    label: 'Bayesian Update',
    markdown: String.raw`
# Conditional MVN Update

## State being updated

The live snapshot is modeled as an adjustment to the latest EOD grid \(g^{eod}\):

$$
g^{live} = g^{eod} + \Delta
$$

where \(\Delta\) follows the PCA prior from the previous section.

## Observation staleness -> observation noise

For an observation with age \(a_i\) minutes and half-life \(h\):

$$
\text{decay}_i = \exp\left(-\log 2 \cdot \frac{a_i}{h}\right)
$$

The stored \`staleness_weight\` is the inverse decay:

$$
\text{staleness weight}_i =
\frac{1}{\max(\text{decay}_i, 10^{-6})}
= 2^{a_i / h}
$$

and the observation-noise multiplier is:

$$
\sigma^{obs}_i =
\text{base\_noise\_bpvol} \times \text{staleness weight}_i
$$

So older trades are not downweighted directly; instead their assumed observation noise increases exponentially with age.

## Continuous-observation path

When bilinear weights are available, each trade contributes a row \(H_i\) over the 66 core nodes. Stack those into an observation operator \(H\).

Given observed trade quotes \(q\), the code forms:

$$
y = q - H g^{eod}
$$

and:

$$
\mu_y = H \mu
$$

$$
V_y = H V_k
$$

The residual variance along each observation row uses only the diagonal residual term:

$$
d_i = \sum_{j=1}^{66} H_{i,j}^2 D_j
$$

and total observation noise is:

$$
R_{ii} = d_i + \sigma^{obs}_i
$$

## Legacy node-aggregation path

If observations have already been collapsed to core nodes, the script first aggregates multiple trades on the same node using precision weights:

$$
\bar{q}_n =
\frac{\sum_i q_i / \sigma_i}{\sum_i 1 / \sigma_i}
$$

with:

$$
\sigma_i = \text{base\_noise\_bpvol} \times \text{staleness weight}_i
$$

and effective node noise:

$$
\sigma^{eff}_n = \frac{1}{\sum_i 1 / \sigma_i}
$$

The legacy \(H\) is then just a selection matrix over observed nodes.

## Posterior factor update

With observed-factor loadings \(V_y\), diagonal factor covariance \(\Lambda_k\), and diagonal observation covariance \(R\), the code computes:

$$
\Pi_{post} = V_y^{\top} R^{-1} V_y + \Lambda_k^{-1}
$$

$$
\Sigma_{post} = \Pi_{post}^{-1}
$$

$$
m_{post} =
\Sigma_{post} V_y^{\top} R^{-1} (y - \mu_y)
$$

This is exactly what \`conditional_mvn_update(...)\` calls \`posterior_precision\`, \`posterior_cov\`, and \`posterior_mean\`.

## Reconstructed live grid

The posterior expected surface change is:

$$
\widehat{\Delta} = \mu + V_k m_{post}
$$

and the pre-anchor live grid is:

$$
g^{live}_{pre-anchor} = g^{eod} + \widehat{\Delta}
$$

## Confidence metric

The displayed confidence is not a posterior probability. It is a nodewise heuristic derived from predictive standard deviation relative to historical total standard deviation.

The predictive variance is:

$$
\text{pred var}_j =
\left[ V_k \Sigma_{post} V_k^{\top} \right]_{j,j} + D_j
$$

and the UI confidence is:

$$
\text{confidence}_j =
\operatorname{clip}\left(
1 - \sqrt{
\frac{\text{pred var}_j}
\max(\text{total var}_j, 10^{-10})
},
0, 1
\right)
$$

If there are no observations at all, the function returns:

- \`live_grid = eod_grid\`
- \`delta_grid = 0\`
- \`posterior_factors = 0\`
- \`confidence = 0\`
`,
  },
  {
    id: 'anchors',
    label: 'Anchors',
    markdown: String.raw`
# Direct Anchors and Residual Propagation

## Why this exists

The raw posterior smooths all observations through the PCA factor structure. The code then adds an explicit override layer to keep near-exact direct observations from being washed out.

## Which observations become direct anchors

An observation is treated as a direct anchor if its dominant core-node weight is at least:

$$
\max_j H_{i,j} \ge 0.95
$$

That threshold is controlled by \`DIRECT_OBSERVATION_ANCHOR_MIN_WEIGHT\`.

## Anchor value per node

If multiple direct-anchor observations hit the same node, they are aggregated using the same precision logic as above:

$$
\text{anchor}_n =
\frac{\sum_i q_i / \sigma_i}{\sum_i 1 / \sigma_i}
$$

## Residual against posterior

For each anchor node \(a\), the code computes:

$$
r_a = \text{anchor}_a - g^{live}_{pre-anchor}(a)
$$

## Propagation kernel

For every target core node \(j\), each anchor contributes an exponential distance weight:

$$
w_{a \to j} = \exp\left(-\frac{d(a,j)}{\ell}\right)
$$

with:

- \(d(a,j)\) = same log-space distance metric used in mapping
- \(\ell =\) \`DIRECT_ANCHOR_PROPAGATION_LENGTH_SCALE\` (default 0.7)

The propagated residual is:

$$
\text{prop residual}_j =
\frac{\sum_a w_{a \to j} r_a}
\alpha + \sum_a w_{a \to j}}
$$

where:

$$
\alpha = \text{DIRECT_ANCHOR_PROPAGATION_PRIOR_WEIGHT}
$$

The stored \`propagation_factor\` is:

$$
\text{prop factor}_j =
\frac{\sum_a w_{a \to j}}
\alpha + \sum_a w_{a \to j}}
$$

## Final order of operations

1. run PCA posterior update
2. add propagated residuals to every core node
3. hard-overwrite anchor nodes with their aggregated observed values

So the final anchored node value is exactly the aggregated direct observation, not a blend.

## Source labeling in stored metadata

For each core node:

- \`direct_observation\` if that node has at least one direct anchor
- \`propagated\` if there were observations somewhere in the snapshot but none directly on that node
- \`prior\` if no observations exist at all

The dashboard later relabels non-core display nodes as \`interpolated\`.
`,
  },
  {
    id: 'premiums',
    label: 'Premiums',
    markdown: String.raw`
# Premium Surface and Stored Node Metadata

## Repricing the live surface

Once the final live core grid is built, the script constructs a QuantLib normal-volatility matrix:

$$
\sigma^{N}_{node} = \frac{\text{bpvol}_{node}}{10{,}000}
$$

and plugs that into a \`ql.SwaptionVolatilityMatrix(..., ql.Normal)\`.

## Query used for each node

For each core node \((expiry, tenor)\), the code resolves:

- curve = \`USD-SOFR-1D\`
- shorthand = \`"{expiry}{tenor}"\`
- structure = \`STRADDLE\`
- strike = \`ATMF\`
- notional = 100mm default

The canonical premium metric taken from the resolved value map is:

$$
\text{premium bps} = \text{IRSwaptionValue.FWD\_PREM}
$$

Then:

$$
\text{premium dollars} =
\frac{\text{premium bps}}{10{,}000} \times \text{notional}
$$

## EOD premium comparison

The script computes the same premium map on:

1. the live anchored grid
2. the reference EOD grid

and stores:

$$
\Delta \text{premium bps} =
\text{premium bps}^{live} - \text{premium bps}^{eod}
$$

## Stored per-node metadata

Each core node gets a metadata payload containing, among other things:

- \`source\`
- \`confidence\`
- \`change_bpvol\`
- \`staleness_minutes\`
- \`premium\`
- \`premium_bps\`
- \`eod_premium\`
- \`eod_premium_bps\`
- \`change_premium_bps\`
- \`observation_count\`
- \`direct_observation_count\`
- \`weighted_observation_count\`
- \`last_propagated_from\`
- \`propagation_factor\`
- \`contributing_trades\`
- \`last_observation_time\`
- \`last_observation\`

## Frontend premium fallback

If \`change_premium_bps\` is missing for a display node, the dashboard can estimate a reference-premium change by assuming premium scales linearly with vol:

$$
\widehat{\text{premium}}^{ref}_{bps} =
\text{premium}^{live}_{bps} \times
\frac{\text{vol}^{ref}}
{\text{vol}^{live}}
$$

$$
\widehat{\Delta \text{premium}}_{bps} =
\text{premium}^{live}_{bps} - \widehat{\text{premium}}^{ref}_{bps}
$$

That estimate is a UI fallback, not a stored calibration output.
`,
  },
  {
    id: 'sessions',
    label: 'Sessions + UI',
    markdown: String.raw`
# Session Resolution, Snapshot Kinds, and UI Read Logic

## Snapshot kinds

The stored snapshot kinds are:

- \`intraday\`
- \`close_pca\`
- \`close_mdp\`

### \`intraday\`

Uses same-day mapped observations plus the PCA update path described above.

### \`close_pca\`

Freezes a closing snapshot from the same PCA+observation pipeline.

### \`close_mdp\`

Stores the direct MDP close grid. For these snapshots the metadata is deterministic:

- \`source = mdp_close\`
- \`confidence = 1.0\`
- \`staleness_minutes = 0.0\`

## Session resolution in the dashboard

All session logic is in ET:

- before 07:00 ET on a business day -> \`preopen_close\`
- between 07:00 and 17:00 ET -> \`live\`
- after 17:00 ET -> \`eod_close\`
- Saturday/Sunday -> \`weekend_close\`
- explicit \`date=YYYY-MM-DD\` query -> \`historical\`

If no current-day snapshot exists during live hours, the session downgrades to \`prior_close\`.

## Snapshot preference order

For live sessions:

1. \`intraday\`
2. \`close_pca\`
3. \`close_mdp\`

For closing / historical sessions:

1. \`close_pca\`
2. \`close_mdp\`
3. \`intraday\`

Closing views also request a comparison snapshot against \`close_mdp\` when the primary snapshot is not already \`close_mdp\`.

## Read-path interpolation to display nodes

The dashboard does not ask the backend for an 11 x 8 calibrated state. Instead it interpolates missing display-node values from the surrounding core corners using the same log-space bilinear weights concept.

For non-core nodes:

- \`source = interpolated\`
- interpolated confidence is scaled by 0.85
- \`observationCount = 0\`
- UI \`propagationFactor = 0.6\`

The representative last observation is taken from the highest-weight corner, with latest timestamp breaking ties.

## Staleness categories shown in the grid

The frontend labels staleness using:

- live: < 15 minutes
- recent: < 60 minutes
- stale: < 240 minutes
- very stale: < 480 minutes

Special cases:

- \`mdp_close\` is forced to \`recent\`
- \`prior\` is forced to \`very_stale\`
- \`interpolated\` is forced to \`stale\`

## Quadrant classification

Displayed cells are tagged by a simple geometry rule:

- expiry boundary = 1.5Y
- tenor boundary = 7.5Y
- tolerance = 0.5Y

Anything near a boundary is \`BOUNDARY\`; otherwise the grid is split into short/long expiry x short/long tenor quadrants.

## Critical transparency: current config behavior

The dashboard exposes a "Configure" panel, but the current read path does **not** recompute the live surface from those settings.

Implementation facts:

- \`/api/vol-grid/calibration-config\` stores the config in process memory only
- \`buildVolGridSurface(...)\` currently does:

~~~ts
const _ = params.config
~~~

- \`/api/vol-grid/surface\` and \`/api/vol-grid/calibration-trades\` resolve stored snapshots/observations mainly by preset, date, and snapshot-kind preference

So today:

- preset changes matter because snapshots are keyed by preset
- ad hoc config edits are not a persisted recalibration job
- server restarts will reset the in-memory config

This is deliberate to state explicitly because the UI can look more dynamic than the underlying read path actually is.
`,
  },
  {
    id: 'repro',
    label: 'Repro Steps',
    markdown: String.raw`
# Reproduction Recipe and Validation Checklist

## Minimal reproduction sequence

1. Load or backfill EOD history into \`arbs_atmf_grid_eod_history_v1\`.
2. Fit \`SurfacePCAModel\` on daily core-grid changes over the chosen lookback window.
3. Pull same-day \`STRADDLE\` / \`OUTRIGHT\` package rows and leg detail.
4. Rebuild \`StraddleObservation\` objects, including manual and inferred incomplete straddles.
5. Apply preset filter:
   - platform type
   - action allowlist
   - valid coordinates
   - intraday max staleness
6. Map each observation to:
   - nearest display node
   - bilinear core-grid weights
7. Compute staleness-based observation noise.
8. Run the conditional MVN update against the latest EOD grid.
9. Apply direct-anchor aggregation, residual propagation, then hard anchor overwrite.
10. Reprice ATMF premiums off the final live grid.
11. Write snapshot + observations.
12. On the dashboard side, interpolate the stored core snapshot onto the extended display grid.

## Skeleton pseudocode

~~~python
model, _ = fit_surface_pca_from_eod_grids(eod_levels_df, n_components=5)
raw_obs = fetch_straddle_observations(engine, as_of_date)
selected, filtered_out = filter_observations_for_preset(
    raw_obs,
    preset='idb_straddles',
    max_staleness_minutes=480,
    as_of_ts=snapshot_ts,
)
mapped = map_observations_to_grid(
    selected,
    tenor_weight=0.7,
    use_continuous_observations=True,
)
mapped = compute_staleness_weights(
    mapped,
    as_of_ts=snapshot_ts,
    half_life_minutes=120,
)
update, node_metadata, premiums, last_obs = build_live_grid(
    model,
    eod_grid,
    mapped,
    base_noise_bpvol=0.5,
    curve_name='USD-SOFR-1D',
    surface_type='atmf_normal',
    pricing_date=eod_as_of_date,
    tenor_weight=0.7,
    use_continuous_observations=True,
)
~~~

## Recommended parity checks

- Verify the PCA training window end date equals the anchor EOD date.
- Check the core-grid vector ordering matches \`SURFACE_NODE_KEYS\` exactly.
- For a sampled off-grid trade, confirm the 1-4 bilinear weights sum to 1.
- Recompute posterior factors and confirm stored \`pca_factors\` parity.
- For a direct-anchor node, verify the final live value equals the precision-weighted anchor average exactly.
- For a propagated-only node, verify the residual-propagation term is applied after the PCA posterior but before final metadata is written.
- Reprice live and EOD premiums on the same 100mm notional assumption.
- Confirm the dashboard 3Y and 7Y columns are reproduced only after frontend interpolation.

## Known modeling caveats

- Confidence is a normalized uncertainty ratio, not a calibrated probability.
- Residual observation variance is diagonal; cross-node residual covariance is ignored.
- Direct anchors partially bypass the pure Bayesian posterior by design.
- The display grid contains interpolated tenors that are not part of the stored latent state.
- The dashboard configuration API is currently an in-memory control surface, not a persistent recalibration service.
`,
  },
]
