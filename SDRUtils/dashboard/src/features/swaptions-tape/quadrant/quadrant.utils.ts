// Core utilities for vol grid quadrant framework
import type { TapeRow } from '../types/trade.types';
import type {
  VolGridQuadrant,
  QuadrantConfig,
  QuadrantClassification,
  QuadrantFlowSnapshot,
  FlowDirection,
  GridFlowState,
  CrossQuadrantSignal,
  FlowRegime,
  FlowRegimeId,
  QuadrantAnomaly,
  TradeQuadrantContext,
  QuadrantMeta,
} from '../types/quadrant.types';
import { DEFAULT_QUADRANT_CONFIG, DEFAULT_QUADRANT_META, FLOW_REGIMES } from './quadrant.config';

// ---------------------------------------------------------------------------
// Tenor label → years conversion
// ---------------------------------------------------------------------------

const TENOR_PARSE_REGEX = /^(\d+(?:\.\d+)?)\s*(D|W|M|Y)$/i;

/** Convert a tenor label (e.g. "2Y", "6M", "30Y") to fractional years. */
export function tenorLabelToYears(label: string | null | undefined): number | null {
  if (!label) return null;
  const trimmed = label.trim().toUpperCase();

  // Handle "spot" as 0
  if (trimmed === 'SPOT' || trimmed === '0D') return 0;

  const match = trimmed.match(TENOR_PARSE_REGEX);
  if (!match) return null;

  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount < 0) return null;

  const unit = match[2];
  switch (unit) {
    case 'D':
      return amount / 365;
    case 'W':
      return (amount * 7) / 365;
    case 'M':
      return amount / 12;
    case 'Y':
      return amount;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Quadrant classification
// ---------------------------------------------------------------------------

/** Classify a trade into a vol grid quadrant based on its expiry and tenor. */
export function classifyQuadrant(
  forwardLabel: string | null | undefined,
  tenorLabel: string | null | undefined,
  config: QuadrantConfig = DEFAULT_QUADRANT_CONFIG,
): QuadrantClassification {
  const expiryYears = tenorLabelToYears(forwardLabel);
  const tenorYears = tenorLabelToYears(tenorLabel);

  if (expiryYears === null || tenorYears === null) {
    return { quadrant: 'BOUNDARY', expiryYears, tenorYears };
  }

  // "spot" trades (expiry = 0) treated as short expiry
  const effectiveExpiry = expiryYears === 0 ? 0 : expiryYears;

  const { expiryBoundaryYears, tenorBoundaryYears, boundaryToleranceYears } = config;

  const nearExpiryBoundary =
    Math.abs(effectiveExpiry - expiryBoundaryYears) <= boundaryToleranceYears;
  const nearTenorBoundary =
    Math.abs(tenorYears - tenorBoundaryYears) <= boundaryToleranceYears;

  // Check if near any boundary
  if (nearExpiryBoundary || nearTenorBoundary) {
    const adjacent: VolGridQuadrant[] = [];
    if (nearExpiryBoundary && nearTenorBoundary) {
      adjacent.push('ULC', 'URC', 'LLC', 'LRC');
    } else if (nearExpiryBoundary) {
      if (tenorYears < tenorBoundaryYears) {
        adjacent.push('ULC', 'LLC');
      } else {
        adjacent.push('URC', 'LRC');
      }
    } else {
      if (effectiveExpiry < expiryBoundaryYears) {
        adjacent.push('ULC', 'URC');
      } else {
        adjacent.push('LLC', 'LRC');
      }
    }
    return { quadrant: 'BOUNDARY', adjacentQuadrants: adjacent, expiryYears, tenorYears };
  }

  // Clear classification
  const isShortExpiry = effectiveExpiry < expiryBoundaryYears;
  const isShortTenor = tenorYears < tenorBoundaryYears;

  let quadrant: VolGridQuadrant;
  if (isShortExpiry && isShortTenor) quadrant = 'ULC';
  else if (isShortExpiry && !isShortTenor) quadrant = 'URC';
  else if (!isShortExpiry && isShortTenor) quadrant = 'LLC';
  else quadrant = 'LRC';

  return { quadrant, expiryYears, tenorYears };
}

/** Classify a TapeRow and return the result. */
export function classifyTradeQuadrant(
  row: TapeRow,
  config?: QuadrantConfig,
): QuadrantClassification {
  return classifyQuadrant(row.forward_label, row.tenor_label, config);
}

// ---------------------------------------------------------------------------
// Trade direction inference
// ---------------------------------------------------------------------------

/** Infer whether a trade is payer or receiver from its legs. */
export function inferTradeDirection(row: TapeRow): FlowDirection {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  if (legs.length === 0) return 'balanced';

  let payerNotional = 0;
  let receiverNotional = 0;

  for (const leg of legs) {
    const notional = Math.abs(Number(leg.notional) || 0);
    const pt = (leg.product_type || '').toUpperCase();
    if (pt.includes('PAYER') || pt.includes('CALL')) {
      payerNotional += notional;
    } else if (pt.includes('RECEIVER') || pt.includes('PUT')) {
      receiverNotional += notional;
    }
  }

  if (payerNotional === 0 && receiverNotional === 0) return 'balanced';
  if (payerNotional > receiverNotional * 1.1) return 'payer';
  if (receiverNotional > payerNotional * 1.1) return 'receiver';
  return 'balanced';
}

/** Get signed notional: positive for payer, negative for receiver. */
export function signedNotional(row: TapeRow): number {
  const direction = inferTradeDirection(row);
  const notional = Math.abs(Number(row.total_notional) || 0);
  if (direction === 'payer') return notional;
  if (direction === 'receiver') return -notional;
  return 0;
}

// ---------------------------------------------------------------------------
// Flow aggregation
// ---------------------------------------------------------------------------

/** Create an empty flow snapshot for a quadrant. */
function emptySnapshot(quadrant: VolGridQuadrant): QuadrantFlowSnapshot {
  return {
    quadrant,
    tradeCount: 0,
    grossNotional: 0,
    netNotional: 0,
    netGrossRatio: 0,
    totalPremium: 0,
    paceVsBaseline: 1.0,
    dominantDirection: 'balanced',
    dominantStructure: '',
    trades: [],
  };
}

/** Aggregate trades into a flow snapshot for a single quadrant. */
export function aggregateQuadrantFlow(
  quadrant: VolGridQuadrant,
  trades: TapeRow[],
  baselineTradeCount?: number,
): QuadrantFlowSnapshot {
  if (trades.length === 0) return emptySnapshot(quadrant);

  let grossNotional = 0;
  let netNotional = 0;
  let totalPremium = 0;
  const structureCounts: Record<string, number> = {};

  for (const trade of trades) {
    const absNotional = Math.abs(Number(trade.total_notional) || 0);
    grossNotional += absNotional;
    netNotional += signedNotional(trade);
    totalPremium += Math.abs(Number(trade.total_premium) || 0);

    const pkg = trade.package_type || 'OUTRIGHT';
    structureCounts[pkg] = (structureCounts[pkg] || 0) + 1;
  }

  const netGrossRatio = grossNotional > 0 ? Math.abs(netNotional) / grossNotional : 0;

  let dominantDirection: FlowDirection = 'balanced';
  if (netGrossRatio > 0.15) {
    dominantDirection = netNotional > 0 ? 'payer' : 'receiver';
  }

  const dominantStructure = Object.entries(structureCounts)
    .sort((a, b) => b[1] - a[1])[0]?.[0] || '';

  const pace = baselineTradeCount && baselineTradeCount > 0
    ? trades.length / baselineTradeCount
    : 1.0;

  return {
    quadrant,
    tradeCount: trades.length,
    grossNotional,
    netNotional,
    netGrossRatio,
    totalPremium,
    paceVsBaseline: pace,
    dominantDirection,
    dominantStructure,
    trades,
  };
}

// ---------------------------------------------------------------------------
// Grid flow state (all four quadrants)
// ---------------------------------------------------------------------------

/** Group trades by quadrant and compute full grid flow state. */
export function computeGridFlowState(
  trades: TapeRow[],
  config: QuadrantConfig = DEFAULT_QUADRANT_CONFIG,
  baselineCounts?: Record<VolGridQuadrant, number>,
): GridFlowState {
  const buckets: Record<VolGridQuadrant, TapeRow[]> = {
    ULC: [],
    URC: [],
    LLC: [],
    LRC: [],
    BOUNDARY: [],
  };

  for (const trade of trades) {
    const classification = classifyTradeQuadrant(trade, config);
    buckets[classification.quadrant].push(trade);
  }

  const ulc = aggregateQuadrantFlow('ULC', buckets.ULC, baselineCounts?.ULC);
  const urc = aggregateQuadrantFlow('URC', buckets.URC, baselineCounts?.URC);
  const llc = aggregateQuadrantFlow('LLC', buckets.LLC, baselineCounts?.LLC);
  const lrc = aggregateQuadrantFlow('LRC', buckets.LRC, baselineCounts?.LRC);
  const boundary = aggregateQuadrantFlow('BOUNDARY', buckets.BOUNDARY, baselineCounts?.BOUNDARY);

  const crossQuadrantSignals = detectCrossQuadrantSignals(ulc, urc, llc, lrc);
  const { regime, confidence } = detectFlowRegime(ulc, urc, llc, lrc);
  const dominantTheme = buildDominantTheme(ulc, urc, llc, lrc, crossQuadrantSignals, regime);

  return {
    ulc,
    urc,
    llc,
    lrc,
    boundary,
    detectedRegime: regime,
    regimeConfidence: confidence,
    crossQuadrantSignals,
    dominantTheme,
  };
}

// ---------------------------------------------------------------------------
// Cross-quadrant signal detection
// ---------------------------------------------------------------------------

function detectCrossQuadrantSignals(
  ulc: QuadrantFlowSnapshot,
  urc: QuadrantFlowSnapshot,
  llc: QuadrantFlowSnapshot,
  lrc: QuadrantFlowSnapshot,
): CrossQuadrantSignal[] {
  const signals: CrossQuadrantSignal[] = [];
  const ACTIVITY_THRESHOLD = 3; // minimum trades for a quadrant to be considered active

  // URC receiver + LRC payer = steepener
  if (
    urc.tradeCount >= ACTIVITY_THRESHOLD &&
    lrc.tradeCount >= ACTIVITY_THRESHOLD &&
    urc.dominantDirection === 'receiver' &&
    lrc.dominantDirection === 'payer'
  ) {
    const confidence = Math.min(urc.netGrossRatio, lrc.netGrossRatio);
    signals.push({
      signalId: 'URC_rcvr_LRC_payer',
      label: 'URC receiver + LRC payer',
      description:
        'Consistent with curve steepener expression — receiving gamma on long tail while paying vega on long tail. Common with GSE or mortgage hedging flows.',
      quadrants: ['URC', 'LRC'],
      confidence,
    });
  }

  // URC payer + LRC receiver = flattener
  if (
    urc.tradeCount >= ACTIVITY_THRESHOLD &&
    lrc.tradeCount >= ACTIVITY_THRESHOLD &&
    urc.dominantDirection === 'payer' &&
    lrc.dominantDirection === 'receiver'
  ) {
    const confidence = Math.min(urc.netGrossRatio, lrc.netGrossRatio);
    signals.push({
      signalId: 'URC_payer_LRC_rcvr',
      label: 'URC payer + LRC receiver',
      description:
        'Consistent with curve flattener expression — paying gamma on long tail while receiving vega.',
      quadrants: ['URC', 'LRC'],
      confidence,
    });
  }

  // Broad receiver flow (URC + LLC + LRC all receiver)
  if (
    urc.dominantDirection === 'receiver' &&
    llc.dominantDirection === 'receiver' &&
    lrc.dominantDirection === 'receiver' &&
    (urc.tradeCount + llc.tradeCount + lrc.tradeCount) >= ACTIVITY_THRESHOLD * 2
  ) {
    signals.push({
      signalId: 'broad_receiver',
      label: 'Broad receiver flow',
      description:
        'Receiver flow across multiple quadrants suggests risk-off positioning or broad-based rate rally.',
      quadrants: ['URC', 'LLC', 'LRC'],
      confidence: 0.7,
    });
  }

  // Broad payer flow
  if (
    urc.dominantDirection === 'payer' &&
    llc.dominantDirection === 'payer' &&
    lrc.dominantDirection === 'payer' &&
    (urc.tradeCount + llc.tradeCount + lrc.tradeCount) >= ACTIVITY_THRESHOLD * 2
  ) {
    signals.push({
      signalId: 'broad_payer',
      label: 'Broad payer flow',
      description:
        'Payer flow across multiple quadrants suggests risk-on positioning or rate sell-off.',
      quadrants: ['URC', 'LLC', 'LRC'],
      confidence: 0.7,
    });
  }

  // LLC heavy receiver (callable supply)
  if (
    llc.tradeCount >= ACTIVITY_THRESHOLD &&
    llc.dominantDirection === 'receiver' &&
    llc.paceVsBaseline > 1.5 &&
    ulc.paceVsBaseline < 1.0 &&
    urc.paceVsBaseline < 1.0
  ) {
    signals.push({
      signalId: 'LLC_supply_wave',
      label: 'LLC supply wave',
      description:
        'Heavy receiver flow concentrated in LLC with quiet other quadrants — consistent with callable issuance supply.',
      quadrants: ['LLC'],
      confidence: 0.6,
    });
  }

  return signals;
}

// ---------------------------------------------------------------------------
// Flow regime detection
// ---------------------------------------------------------------------------

function matchDirection(
  actual: FlowDirection,
  expected: FlowDirection | 'quiet' | 'any',
  pace: number,
): boolean {
  if (expected === 'any') return true;
  if (expected === 'quiet') return pace < 0.7;
  return actual === expected;
}

function matchIntensity(
  pace: number,
  expected: 'low' | 'moderate' | 'heavy' | 'any',
): boolean {
  if (expected === 'any') return true;
  if (expected === 'low') return pace < 0.8;
  if (expected === 'moderate') return pace >= 0.5 && pace <= 2.0;
  if (expected === 'heavy') return pace > 1.3;
  return true;
}

function detectFlowRegime(
  ulc: QuadrantFlowSnapshot,
  urc: QuadrantFlowSnapshot,
  llc: QuadrantFlowSnapshot,
  lrc: QuadrantFlowSnapshot,
): { regime: FlowRegime | null; confidence: number } {
  let bestRegime: FlowRegime | null = null;
  let bestScore = 0;

  const snapshots = { ulc, urc, llc, lrc };
  const quadrantKeys = ['ulc', 'urc', 'llc', 'lrc'] as const;

  for (const regime of FLOW_REGIMES) {
    let matchCount = 0;
    let totalChecks = 0;

    for (const q of quadrantKeys) {
      const snap = snapshots[q];
      totalChecks += 2;
      if (matchDirection(snap.dominantDirection, regime.signature[q], snap.paceVsBaseline)) {
        matchCount++;
      }
      if (matchIntensity(snap.paceVsBaseline, regime.intensity[q])) {
        matchCount++;
      }
    }

    const score = totalChecks > 0 ? matchCount / totalChecks : 0;
    if (score > bestScore && score >= 0.6) {
      bestScore = score;
      bestRegime = regime;
    }
  }

  return { regime: bestRegime, confidence: bestScore };
}

// ---------------------------------------------------------------------------
// Narrative generation
// ---------------------------------------------------------------------------

function describeQuadrant(snap: QuadrantFlowSnapshot): string {
  if (snap.tradeCount === 0) return 'quiet';
  const parts: string[] = [];
  if (snap.paceVsBaseline > 1.5) parts.push('active');
  else if (snap.paceVsBaseline < 0.5) parts.push('quiet');
  else parts.push('normal');

  if (snap.dominantDirection !== 'balanced') {
    parts.push(`net ${snap.dominantDirection} flow`);
  }
  return parts.join(' — ');
}

function buildDominantTheme(
  ulc: QuadrantFlowSnapshot,
  urc: QuadrantFlowSnapshot,
  llc: QuadrantFlowSnapshot,
  lrc: QuadrantFlowSnapshot,
  signals: CrossQuadrantSignal[],
  regime: FlowRegime | null,
): string {
  if (regime) {
    return `${regime.label}: ${regime.description}`;
  }

  if (signals.length > 0) {
    return signals[0].description;
  }

  // Find most active quadrant
  const quads = [
    { label: 'ULC', snap: ulc },
    { label: 'URC', snap: urc },
    { label: 'LLC', snap: llc },
    { label: 'LRC', snap: lrc },
  ];
  const mostActive = quads.sort((a, b) => b.snap.grossNotional - a.snap.grossNotional)[0];

  if (mostActive.snap.tradeCount === 0) return 'No significant flow today';

  const desc = describeQuadrant(mostActive.snap);
  return `Dominant flow: ${mostActive.label} (${desc})`;
}

// ---------------------------------------------------------------------------
// Anomaly detection
// ---------------------------------------------------------------------------

export function detectQuadrantAnomalies(
  current: GridFlowState,
  historicalBaselines?: Record<VolGridQuadrant, { avgPace: number; avgNetGrossRatio: number; avgPremiumShare: number; pctDaysReceiver: number }>,
): QuadrantAnomaly[] {
  const anomalies: QuadrantAnomaly[] = [];
  if (!historicalBaselines) return anomalies;

  const quadrants: { key: VolGridQuadrant; snap: QuadrantFlowSnapshot }[] = [
    { key: 'ULC', snap: current.ulc },
    { key: 'URC', snap: current.urc },
    { key: 'LLC', snap: current.llc },
    { key: 'LRC', snap: current.lrc },
  ];

  const totalPremium =
    current.ulc.totalPremium +
    current.urc.totalPremium +
    current.llc.totalPremium +
    current.lrc.totalPremium;

  for (const { key, snap } of quadrants) {
    const baseline = historicalBaselines[key];
    if (!baseline) continue;

    // Volume anomaly
    if (snap.paceVsBaseline > 2.5) {
      anomalies.push({
        type: 'volume',
        quadrant: key,
        severity: snap.paceVsBaseline > 3.5 ? 'extreme' : 'notable',
        message: `${key} is at ${snap.paceVsBaseline.toFixed(1)}x normal pace today`,
        detail: `${snap.tradeCount} trades vs typical baseline`,
        currentValue: snap.paceVsBaseline,
        historicalBaseline: 1.0,
      });
    }

    // Direction anomaly
    const isReceiver = snap.dominantDirection === 'receiver';
    const isPayer = snap.dominantDirection === 'payer';
    const expectedReceiverPct = baseline.pctDaysReceiver;

    if (isPayer && expectedReceiverPct > 0.7) {
      anomalies.push({
        type: 'direction',
        quadrant: key,
        severity: 'notable',
        message: `${key} is net payer today — unusual (net receiver ${Math.round(expectedReceiverPct * 100)}% of days)`,
        detail: `Net notional: +${formatCompactNotional(snap.netNotional)}`,
        currentValue: snap.netNotional,
        historicalBaseline: -1,
      });
    } else if (isReceiver && expectedReceiverPct < 0.3) {
      anomalies.push({
        type: 'direction',
        quadrant: key,
        severity: 'notable',
        message: `${key} is net receiver today — unusual (net payer ${Math.round((1 - expectedReceiverPct) * 100)}% of days)`,
        detail: `Net notional: ${formatCompactNotional(snap.netNotional)}`,
        currentValue: snap.netNotional,
        historicalBaseline: 1,
      });
    }

    // Premium concentration anomaly
    if (totalPremium > 0) {
      const premiumShare = snap.totalPremium / totalPremium;
      if (premiumShare > baseline.avgPremiumShare * 1.8 && premiumShare > 0.4) {
        anomalies.push({
          type: 'premium',
          quadrant: key,
          severity: 'notable',
          message: `${key} premium concentration is ${Math.round(premiumShare * 100)}% of total grid today (normal: ${Math.round(baseline.avgPremiumShare * 100)}%)`,
          detail: 'Expensive activity concentrated in this quadrant',
          currentValue: premiumShare,
          historicalBaseline: baseline.avgPremiumShare,
        });
      }
    }
  }

  // Cross-quadrant anomaly: co-directional flow
  const urcDir = current.urc.dominantDirection;
  const llcDir = current.llc.dominantDirection;
  if (
    urcDir === llcDir &&
    urcDir !== 'balanced' &&
    current.urc.tradeCount >= 3 &&
    current.llc.tradeCount >= 3
  ) {
    anomalies.push({
      type: 'cross_quadrant',
      quadrant: 'URC',
      severity: 'notable',
      message: `URC and LLC are both net ${urcDir} today — broad-based ${urcDir} flow across the grid`,
      detail: `URC: ${formatCompactNotional(current.urc.netNotional)}, LLC: ${formatCompactNotional(current.llc.netNotional)}`,
      currentValue: 0,
      historicalBaseline: 0,
    });
  }

  return anomalies;
}

// ---------------------------------------------------------------------------
// Trade-level quadrant context enrichment
// ---------------------------------------------------------------------------

/** Build quadrant context enrichment for a single trade. */
export function buildTradeQuadrantContext(
  trade: TapeRow,
  allTrades: TapeRow[],
  config: QuadrantConfig = DEFAULT_QUADRANT_CONFIG,
  meta?: Record<VolGridQuadrant, QuadrantMeta>,
): TradeQuadrantContext {
  const classification = classifyTradeQuadrant(trade, config);
  const quadrantMeta = (meta || DEFAULT_QUADRANT_META)[classification.quadrant];

  // Build daily grid state for context
  const gridState = computeGridFlowState(allTrades, config);
  const quadrantFlow = getQuadrantSnapshot(gridState, classification.quadrant);

  // Does this trade reinforce or counter the direction?
  const tradeDirection = inferTradeDirection(trade);
  const reinforcesDirection =
    quadrantFlow.dominantDirection === 'balanced' ||
    tradeDirection === 'balanced' ||
    tradeDirection === quadrantFlow.dominantDirection;

  // Share of quadrant
  const tradeNotional = Math.abs(Number(trade.total_notional) || 0);
  const shareOfQuadrant =
    quadrantFlow.grossNotional > 0 ? tradeNotional / quadrantFlow.grossNotional : 0;

  // Simultaneous activity (±30 min window)
  const tradeTime = new Date(trade.execution_start).getTime();
  const WINDOW_MS = 30 * 60 * 1000;
  const nearbyTrades = allTrades.filter((t) => {
    if (t.package_id === trade.package_id) return false;
    const tTime = new Date(t.execution_start).getTime();
    return Math.abs(tTime - tradeTime) <= WINDOW_MS;
  });

  const nearbyByQuadrant: Record<VolGridQuadrant, TapeRow[]> = {
    ULC: [],
    URC: [],
    LLC: [],
    LRC: [],
    BOUNDARY: [],
  };
  for (const t of nearbyTrades) {
    const c = classifyTradeQuadrant(t, config);
    if (c.quadrant !== classification.quadrant) {
      nearbyByQuadrant[c.quadrant].push(t);
    }
  }

  const simultaneousActivity = (['ULC', 'URC', 'LLC', 'LRC', 'BOUNDARY'] as VolGridQuadrant[])
    .filter((q) => nearbyByQuadrant[q].length > 0)
    .map((q) => {
      const trades = nearbyByQuadrant[q];
      const net = trades.reduce((sum, t) => sum + signedNotional(t), 0);
      return {
        quadrant: q,
        tradeCount: trades.length,
        netNotional: net,
        direction: (Math.abs(net) < 1e6 ? 'balanced' : net > 0 ? 'payer' : 'receiver') as FlowDirection,
      };
    });

  // Check if cross-quadrant pattern exists
  const crossQuadrantPattern = gridState.crossQuadrantSignals.find((s) =>
    s.quadrants.includes(classification.quadrant),
  ) || null;

  return {
    classification,
    quadrantMeta,
    quadrantFlow,
    reinforcesDirection,
    shareOfQuadrant,
    simultaneousActivity,
    crossQuadrantPattern,
  };
}

function getQuadrantSnapshot(
  state: GridFlowState,
  quadrant: VolGridQuadrant,
): QuadrantFlowSnapshot {
  switch (quadrant) {
    case 'ULC': return state.ulc;
    case 'URC': return state.urc;
    case 'LLC': return state.llc;
    case 'LRC': return state.lrc;
    case 'BOUNDARY': return state.boundary;
  }
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatCompactNotional(value: number): string {
  const abs = Math.abs(value);
  const sign = value >= 0 ? '+' : '-';
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}bn`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(0)}mm`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}k`;
  return `${sign}${abs.toFixed(0)}`;
}

export function formatPremium(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}m`;
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`;
  return abs.toFixed(0);
}

export function formatPace(pace: number): string {
  if (pace < 0.01) return '—';
  return `${pace.toFixed(1)}x`;
}

/** Generate a one-line narrative for a quadrant snapshot. */
export function quadrantNarrative(snap: QuadrantFlowSnapshot): string {
  if (snap.tradeCount === 0) return 'quiet';
  return describeQuadrant(snap);
}
