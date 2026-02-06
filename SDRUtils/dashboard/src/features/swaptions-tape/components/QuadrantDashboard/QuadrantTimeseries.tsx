// Quadrant-level timeseries view: volume, net flow, premium share over time
import { memo, useMemo, useState } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  Area,
  AreaChart,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from 'recharts';
import type { TapeRow } from '../../types/trade.types';
import type { VolGridQuadrant, QuadrantConfig } from '../../types/quadrant.types';
import { classifyTradeQuadrant, formatCompactNotional, signedNotional } from '../../quadrant/quadrant.utils';
import { QUADRANT_COLORS, DEFAULT_QUADRANT_CONFIG } from '../../quadrant/quadrant.config';

export type QuadrantTimeseriesProps = {
  rows: TapeRow[];
  config?: QuadrantConfig;
};

type MetricMode = 'net_notional' | 'gross_notional' | 'trade_count' | 'premium' | 'premium_share';

type DailyQuadrantPoint = {
  date: string;
  ulc_gross: number;
  ulc_net: number;
  ulc_count: number;
  ulc_premium: number;
  urc_gross: number;
  urc_net: number;
  urc_count: number;
  urc_premium: number;
  llc_gross: number;
  llc_net: number;
  llc_count: number;
  llc_premium: number;
  lrc_gross: number;
  lrc_net: number;
  lrc_count: number;
  lrc_premium: number;
  // Premium shares
  ulc_pshare: number;
  urc_pshare: number;
  llc_pshare: number;
  lrc_pshare: number;
  // Divergence
  urc_lrc_divergence: number;
};

const METRIC_OPTIONS: { key: MetricMode; label: string }[] = [
  { key: 'net_notional', label: 'Net Notional' },
  { key: 'gross_notional', label: 'Gross Notional' },
  { key: 'trade_count', label: 'Trade Count' },
  { key: 'premium', label: 'Premium' },
  { key: 'premium_share', label: 'Premium Share (%)' },
];

function getDateKey(isoString: string): string {
  return isoString.slice(0, 10);
}

export const QuadrantTimeseries = memo(function QuadrantTimeseries({
  rows,
  config = DEFAULT_QUADRANT_CONFIG,
}: QuadrantTimeseriesProps) {
  const [metric, setMetric] = useState<MetricMode>('net_notional');

  // Aggregate rows by date and quadrant
  const dailyData = useMemo(() => {
    const byDate: Record<string, Record<VolGridQuadrant, { gross: number; net: number; count: number; premium: number }>> = {};

    for (const row of rows) {
      const date = getDateKey(row.execution_start);
      const classification = classifyTradeQuadrant(row, config);
      const q = classification.quadrant === 'BOUNDARY' ? 'URC' : classification.quadrant; // fold boundary into nearest

      if (!byDate[date]) {
        byDate[date] = {
          ULC: { gross: 0, net: 0, count: 0, premium: 0 },
          URC: { gross: 0, net: 0, count: 0, premium: 0 },
          LLC: { gross: 0, net: 0, count: 0, premium: 0 },
          LRC: { gross: 0, net: 0, count: 0, premium: 0 },
          BOUNDARY: { gross: 0, net: 0, count: 0, premium: 0 },
        };
      }

      const d = byDate[date][q];
      d.gross += Math.abs(Number(row.total_notional) || 0);
      d.net += signedNotional(row);
      d.count += 1;
      d.premium += Math.abs(Number(row.total_premium) || 0);
    }

    const dates = Object.keys(byDate).sort();
    return dates.map((date) => {
      const d = byDate[date];
      const totalPremium = d.ULC.premium + d.URC.premium + d.LLC.premium + d.LRC.premium;
      const point: DailyQuadrantPoint = {
        date,
        ulc_gross: d.ULC.gross,
        ulc_net: d.ULC.net,
        ulc_count: d.ULC.count,
        ulc_premium: d.ULC.premium,
        urc_gross: d.URC.gross,
        urc_net: d.URC.net,
        urc_count: d.URC.count,
        urc_premium: d.URC.premium,
        llc_gross: d.LLC.gross,
        llc_net: d.LLC.net,
        llc_count: d.LLC.count,
        llc_premium: d.LLC.premium,
        lrc_gross: d.LRC.gross,
        lrc_net: d.LRC.net,
        lrc_count: d.LRC.count,
        lrc_premium: d.LRC.premium,
        ulc_pshare: totalPremium > 0 ? (d.ULC.premium / totalPremium) * 100 : 0,
        urc_pshare: totalPremium > 0 ? (d.URC.premium / totalPremium) * 100 : 0,
        llc_pshare: totalPremium > 0 ? (d.LLC.premium / totalPremium) * 100 : 0,
        lrc_pshare: totalPremium > 0 ? (d.LRC.premium / totalPremium) * 100 : 0,
        urc_lrc_divergence: d.URC.net - d.LRC.net,
      };
      return point;
    });
  }, [rows, config]);

  if (dailyData.length === 0) {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 text-[11px] text-slate-500">
        No data for quadrant timeseries.
      </div>
    );
  }

  const getDataKeys = (): { ulc: string; urc: string; llc: string; lrc: string } => {
    switch (metric) {
      case 'net_notional': return { ulc: 'ulc_net', urc: 'urc_net', llc: 'llc_net', lrc: 'lrc_net' };
      case 'gross_notional': return { ulc: 'ulc_gross', urc: 'urc_gross', llc: 'llc_gross', lrc: 'lrc_gross' };
      case 'trade_count': return { ulc: 'ulc_count', urc: 'urc_count', llc: 'llc_count', lrc: 'lrc_count' };
      case 'premium': return { ulc: 'ulc_premium', urc: 'urc_premium', llc: 'llc_premium', lrc: 'lrc_premium' };
      case 'premium_share':
      default: return { ulc: 'ulc_pshare', urc: 'urc_pshare', llc: 'llc_pshare', lrc: 'lrc_pshare' };
    }
  };

  const keys = getDataKeys();
  const isStacked = metric === 'premium_share';

  const formatYAxis = (v: number) => {
    if (metric === 'premium_share') return `${v.toFixed(0)}%`;
    if (metric === 'trade_count') return String(v);
    return formatCompactNotional(v);
  };

  // Compute URC-LRC divergence trend
  const lastDivergence = dailyData.length > 0 ? dailyData[dailyData.length - 1].urc_lrc_divergence : 0;
  const firstDivergence = dailyData.length > 1 ? dailyData[0].urc_lrc_divergence : 0;
  const divergenceTrend = lastDivergence > firstDivergence ? 'widening' : lastDivergence < firstDivergence ? 'narrowing' : 'stable';

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      {/* Header with metric selector */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-slate-200">QUADRANT FLOW TIMESERIES</span>
        <div className="flex gap-1">
          {METRIC_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setMetric(opt.key)}
              className={`text-[10px] px-2 py-0.5 rounded ${
                metric === opt.key
                  ? 'bg-slate-700 text-slate-200'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Main chart */}
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer>
          {isStacked ? (
            <AreaChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={formatYAxis} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', fontSize: 11 }}
                labelStyle={{ color: '#94a3b8' }}
                formatter={(value: number) => `${value.toFixed(1)}%`}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Area type="monotone" dataKey={keys.ulc} name="ULC" stackId="1" fill={QUADRANT_COLORS.ULC.accent} fillOpacity={0.6} stroke={QUADRANT_COLORS.ULC.accent} />
              <Area type="monotone" dataKey={keys.urc} name="URC" stackId="1" fill={QUADRANT_COLORS.URC.accent} fillOpacity={0.6} stroke={QUADRANT_COLORS.URC.accent} />
              <Area type="monotone" dataKey={keys.llc} name="LLC" stackId="1" fill={QUADRANT_COLORS.LLC.accent} fillOpacity={0.6} stroke={QUADRANT_COLORS.LLC.accent} />
              <Area type="monotone" dataKey={keys.lrc} name="LRC" stackId="1" fill={QUADRANT_COLORS.LRC.accent} fillOpacity={0.6} stroke={QUADRANT_COLORS.LRC.accent} />
            </AreaChart>
          ) : (
            <ComposedChart data={dailyData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#64748b' }} />
              <YAxis tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={formatYAxis} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', fontSize: 11 }}
                labelStyle={{ color: '#94a3b8' }}
                formatter={(value: number) => formatYAxis(value)}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Line type="monotone" dataKey={keys.ulc} name="ULC" stroke={QUADRANT_COLORS.ULC.accent} strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey={keys.urc} name="URC" stroke={QUADRANT_COLORS.URC.accent} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey={keys.llc} name="LLC" stroke={QUADRANT_COLORS.LLC.accent} strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey={keys.lrc} name="LRC" stroke={QUADRANT_COLORS.LRC.accent} strokeWidth={2} dot={false} />
            </ComposedChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* URC-LRC divergence annotation */}
      {metric === 'net_notional' && dailyData.length > 1 && (
        <div className="mt-2 text-[10px] text-slate-500 border-t border-slate-800 pt-2">
          <span className="text-slate-400 font-medium">URC\u2013LRC Divergence: </span>
          {divergenceTrend === 'widening' && (
            <span className="text-amber-400">widening \u2014 steepener buildup</span>
          )}
          {divergenceTrend === 'narrowing' && (
            <span className="text-blue-400">narrowing \u2014 curve trade unwinding</span>
          )}
          {divergenceTrend === 'stable' && (
            <span className="text-slate-500">stable</span>
          )}
        </div>
      )}
    </div>
  );
});
