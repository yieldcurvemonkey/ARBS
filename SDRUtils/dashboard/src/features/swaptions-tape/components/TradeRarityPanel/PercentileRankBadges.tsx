import { useEffect, useState } from 'react';
import type { MetricDisplayValue, RarityZone } from './rarity.types';

const ZONE_BAR: Record<RarityZone, string> = {
  typical: 'bg-emerald-500',
  notable: 'bg-amber-500',
  rare: 'bg-red-500',
  extreme: 'bg-red-600',
};

const ZONE_BORDER: Record<RarityZone, string> = {
  typical: 'border-emerald-500',
  notable: 'border-amber-500',
  rare: 'border-red-500',
  extreme: 'border-red-600',
};

const ZONE_TEXT: Record<RarityZone, string> = {
  typical: 'text-emerald-300',
  notable: 'text-amber-300',
  rare: 'text-red-300',
  extreme: 'text-red-200',
};

export function PercentileRankBadges({
  metrics,
  primaryKey,
}: {
  metrics: MetricDisplayValue[];
  primaryKey: string;
}) {
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimate(true));
    return () => cancelAnimationFrame(id);
  }, []);

  return (
    <div className="space-y-1">
      {metrics.map((metric) => {
        const isPrimary = metric.key === primaryKey;
        const percentile = metric.percentile ?? 0;
        const zone: RarityZone = metric.zone ?? 'typical';
        const barWidth = metric.showPercentile
          ? `${Math.min(Math.max(percentile, 0), 100)}%`
          : '0%';
        const rowSize = isPrimary ? 'text-[13px]' : 'text-[11px]';
        const rowHeight = isPrimary ? 'h-10' : 'h-9';
        return (
          <div
            key={metric.key}
            className={`flex items-center gap-2 ${rowHeight} ${rowSize} rounded border border-slate-800 bg-slate-950/60 px-2 font-mono text-slate-200 ${
              isPrimary ? `border-l-2 ${ZONE_BORDER[zone]}` : ''
            }`}
          >
            <div className="flex min-w-[140px] items-center gap-1 text-[10px] uppercase tracking-wide text-slate-400">
              {metric.derived && (
                <span className="text-[10px] text-slate-500">(derived)</span>
              )}
              <span>{metric.label}</span>
            </div>
            <div className="min-w-[84px] text-right">
              <span className="text-slate-100">{metric.displayValue}</span>
            </div>
            <div className="min-w-[48px] text-right text-slate-400">
              {metric.showPercentile && metric.percentile !== null
                ? `P${Math.round(metric.percentile)}`
                : '--'}
            </div>
            <div className="relative h-2 w-[120px] overflow-hidden rounded-full bg-slate-800">
              <div
                className={`h-full rounded-full transition-all duration-300 ease-out ${
                  ZONE_BAR[zone]
                }`}
                style={{ width: animate ? barWidth : '0%' }}
              />
            </div>
            <div className={`min-w-[140px] text-[10px] ${ZONE_TEXT[zone]}`}>
              {metric.descriptor}
            </div>
            <div className="min-w-[64px] text-[10px] text-slate-500">
              N={metric.sampleSize}
            </div>
          </div>
        );
      })}
    </div>
  );
}
