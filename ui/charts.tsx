import { useState, type ReactNode } from 'react';
import type { BreakdownRow, Commitment, ConsumptionRow, ForecastMonth, MonthTotal } from './client';
import { formatMoney, formatMonth } from './format';

// The host ships no chart library and a plugin screen may import only its own
// files and React, so the charts are drawn here as SVG. Every chart is drawn in
// a fixed viewBox and scales to its card's width.

const WIDTH = 720;
const PLOT_LEFT = 64;
const PLOT_RIGHT = 16;
const PLOT_TOP = 16;

export const SERIES_COLORS = [
  'var(--azure-cost-series-1)', 'var(--azure-cost-series-2)', 'var(--azure-cost-series-3)',
  'var(--azure-cost-series-4)', 'var(--azure-cost-series-5)', 'var(--azure-cost-series-6)',
  'var(--azure-cost-series-other)',
];

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((candidate) => candidate * magnitude >= value) ?? 10;
  return step * magnitude;
}

function ticks(maximum: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, index) => (maximum / count) * index);
}

interface Hover {
  x: number;
  y: number;
  lines: string[];
}

function Tooltip({ hover }: { hover: Hover | null }) {
  if (!hover) return null;
  const width = Math.max(...hover.lines.map((line) => line.length)) * 6.6 + 16;
  const x = Math.min(Math.max(hover.x - width / 2, 0), WIDTH - width);
  const height = hover.lines.length * 16 + 10;
  const y = Math.max(hover.y - height - 8, 0);
  return (
    <g className="azure-cost-tooltip" pointerEvents="none">
      <rect x={x} y={y} width={width} height={height} rx={4} />
      {hover.lines.map((line, index) => (
        <text key={line + index} x={x + 8} y={y + 18 + index * 16}>{line}</text>
      ))}
    </g>
  );
}

function YAxis({ maximum, plotHeight, currency }: { maximum: number; plotHeight: number; currency: string | null }) {
  return (
    <g className="azure-cost-axis">
      {ticks(maximum).map((tick) => {
        const y = PLOT_TOP + plotHeight - (tick / maximum) * plotHeight;
        return (
          <g key={tick}>
            <line x1={PLOT_LEFT} x2={WIDTH - PLOT_RIGHT} y1={y} y2={y} className="azure-cost-gridline" />
            <text x={PLOT_LEFT - 8} y={y + 4} textAnchor="end">{formatMoney(tick, currency, true)}</text>
          </g>
        );
      })}
    </g>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="azure-cost-legend">
      {items.map((item) => (
        <span key={item.label}>
          <i style={{ background: item.dashed ? 'transparent' : item.color, borderColor: item.color }}
             className={item.dashed ? 'dashed' : undefined} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

/** Monthly spend: actual as bars, amortized as a line, the rest of the year's
 *  forecast as outlined bars. The current month's bar is drawn lighter: it is
 *  still being billed. */
export function TrendChart({ months, forecast, currency }: {
  months: MonthTotal[]; forecast: ForecastMonth[]; currency: string | null;
}) {
  const [hover, setHover] = useState<Hover | null>(null);
  const height = 260;
  const plotHeight = height - PLOT_TOP - 28;
  const forecastByMonth = new Map(forecast.map((month) => [month.month, month]));
  const categories = [
    ...months.map((month) => month.month),
    ...forecast.map((month) => month.month).filter((month) => !months.some((m) => m.month === month)),
  ];
  const actualByMonth = new Map(months.map((month) => [month.month, month]));
  const maximum = niceCeiling(Math.max(
    ...months.map((month) => Math.max(month.actual, month.amortized)),
    ...forecast.map((month) => month.cost), 0));
  const slot = (WIDTH - PLOT_LEFT - PLOT_RIGHT) / Math.max(categories.length, 1);
  const barWidth = Math.min(slot * 0.62, 36);
  const xOf = (index: number) => PLOT_LEFT + slot * index + slot / 2;
  const yOf = (value: number) => PLOT_TOP + plotHeight - (value / maximum) * plotHeight;

  const amortizedPoints = months.map((month) => `${xOf(categories.indexOf(month.month))},${yOf(month.amortized)}`);

  return (
    <svg viewBox={`0 0 ${WIDTH} ${height}`} className="azure-cost-chart" role="img"
         aria-label="Monthly spend, actual and amortized, with forecast">
      <YAxis maximum={maximum} plotHeight={plotHeight} currency={currency} />
      {categories.map((month, index) => {
        const actual = actualByMonth.get(month);
        const projected = forecastByMonth.get(month);
        const x = xOf(index) - barWidth / 2;
        const lines = [formatMonth(month)];
        if (actual) lines.push(`Actual ${formatMoney(actual.actual, currency)}${actual.partial ? ' (so far)' : ''}`);
        if (actual) lines.push(`Amortized ${formatMoney(actual.amortized, currency)}`);
        if (actual?.mom_pct != null) lines.push(`vs previous month ${actual.mom_pct > 0 ? '+' : ''}${actual.mom_pct}%`);
        if (projected) lines.push(`Forecast ${formatMoney(projected.cost, currency)} (${projected.source})`);
        return (
          <g key={month} onMouseEnter={() => setHover({ x: xOf(index), y: yOf(Math.max(actual?.actual ?? 0, projected?.cost ?? 0)), lines })}
             onMouseLeave={() => setHover(null)}>
            <rect x={xOf(index) - slot / 2} y={PLOT_TOP} width={slot} height={plotHeight} fill="transparent" />
            {projected ? (
              <rect x={x} y={yOf(projected.cost)} width={barWidth} height={plotHeight + PLOT_TOP - yOf(projected.cost)}
                    className="azure-cost-forecast-bar" />
            ) : null}
            {actual ? (
              <rect x={x} y={yOf(actual.actual)} width={barWidth} height={plotHeight + PLOT_TOP - yOf(actual.actual)}
                    className={actual.partial ? 'azure-cost-bar partial' : 'azure-cost-bar'} rx={2} />
            ) : null}
            <text x={xOf(index)} y={height - 8} textAnchor="middle" className="azure-cost-axis-label">
              {formatMonth(month, true)}
            </text>
          </g>
        );
      })}
      <polyline points={amortizedPoints.join(' ')} className="azure-cost-line" pointerEvents="none" />
      {months.map((month) => (
        <circle key={month.month} cx={xOf(categories.indexOf(month.month))} cy={yOf(month.amortized)} r={3}
                className="azure-cost-line-point" pointerEvents="none" />
      ))}
      <Tooltip hover={hover} />
    </svg>
  );
}

/** Each month split into the biggest series plus "Other", to see the mix move. */
export function StackedMonthsChart({ rows, groupKey, currency, series = 6 }: {
  rows: ConsumptionRow[]; groupKey: 'service' | 'subscription'; currency: string | null; series?: number;
}) {
  const [hover, setHover] = useState<Hover | null>(null);
  const totalsByName = new Map<string, number>();
  for (const row of rows) {
    const name = row[groupKey] ?? 'Unassigned';
    totalsByName.set(name, (totalsByName.get(name) ?? 0) + row.cost);
  }
  const named = [...totalsByName.entries()].sort((a, b) => b[1] - a[1]).slice(0, series).map(([name]) => name);
  const months = [...new Set(rows.map((row) => row.month))].sort();
  const stacks = months.map((month) => {
    const values = new Map<string, number>();
    for (const row of rows.filter((candidate) => candidate.month === month)) {
      const name = row[groupKey] ?? 'Unassigned';
      const key = named.includes(name) ? name : 'Other';
      values.set(key, (values.get(key) ?? 0) + row.cost);
    }
    return { month, values };
  });
  const keys = [...named, ...(stacks.some((stack) => stack.values.has('Other')) ? ['Other'] : [])];
  const height = 260;
  const plotHeight = height - PLOT_TOP - 28;
  const maximum = niceCeiling(Math.max(0, ...stacks.map((stack) => [...stack.values.values()].reduce((a, b) => a + b, 0))));
  const slot = (WIDTH - PLOT_LEFT - PLOT_RIGHT) / Math.max(months.length, 1);
  const barWidth = Math.min(slot * 0.62, 36);
  const color = (key: string) => key === 'Other' ? SERIES_COLORS[6] : SERIES_COLORS[named.indexOf(key) % 6];

  if (!rows.length) return <p className="text-muted">No consumption cached yet.</p>;

  return (
    <>
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="azure-cost-chart" role="img"
           aria-label={`Monthly spend by ${groupKey}`}>
        <YAxis maximum={maximum} plotHeight={plotHeight} currency={currency} />
        {stacks.map((stack, index) => {
          const x = PLOT_LEFT + slot * index + slot / 2;
          let base = PLOT_TOP + plotHeight;
          const total = [...stack.values.values()].reduce((a, b) => a + b, 0);
          return (
            <g key={stack.month}>
              {keys.map((key) => {
                const value = stack.values.get(key) ?? 0;
                if (!value) return null;
                const segment = (value / maximum) * plotHeight;
                base -= segment;
                const lines = [formatMonth(stack.month), `${key}: ${formatMoney(value, currency)}`,
                  `${Math.round((value / total) * 100)}% of ${formatMoney(total, currency)}`];
                return (
                  <rect key={key} x={x - barWidth / 2} y={base} width={barWidth} height={Math.max(segment, 0.5)}
                        fill={color(key)} className="azure-cost-segment"
                        onMouseEnter={() => setHover({ x, y: base, lines })} onMouseLeave={() => setHover(null)} />
                );
              })}
              <text x={x} y={height - 8} textAnchor="middle" className="azure-cost-axis-label">
                {formatMonth(stack.month, true)}
              </text>
            </g>
          );
        })}
        <Tooltip hover={hover} />
      </svg>
      <Legend items={keys.map((key) => ({ label: key, color: color(key) }))} />
    </>
  );
}

/** Ranked horizontal bars with each row's share and change against last month. */
export function RankedBars({ rows, currency }: { rows: BreakdownRow[]; currency: string | null }) {
  const maximum = Math.max(...rows.map((row) => row.cost), 1);
  return (
    <div className="azure-cost-ranked">
      {rows.map((row) => (
        <div key={row.name} className="azure-cost-ranked-row" title={`${row.name}: ${formatMoney(row.cost, currency)}`}>
          <span className="azure-cost-ranked-name">{row.name}</span>
          <span className="azure-cost-ranked-track">
            <span className="azure-cost-ranked-fill" style={{ width: `${(row.cost / maximum) * 100}%` }} />
          </span>
          <span className="azure-cost-ranked-value">{formatMoney(row.cost, currency, true)}</span>
          <span className="azure-cost-ranked-share">{row.share_pct}%</span>
          <Change pct={row.change_pct} />
        </div>
      ))}
    </div>
  );
}

export function Change({ pct }: { pct: number | null }): ReactNode {
  if (pct == null) return <span className="azure-cost-change text-muted">new</span>;
  const direction = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
  return <span className={`azure-cost-change ${direction}`}>{pct > 0 ? '+' : ''}{pct}%</span>;
}

/** The commitment: consumed so far against the whole, and where the run rate
 *  takes it -- a straight projection from today, with the term's end marked. */
export function BurnDownChart({ commitment, today }: { commitment: Commitment; today: Date }) {
  const height = 220;
  const plotHeight = height - PLOT_TOP - 28;
  const start = commitment.start ? new Date(commitment.start) : null;
  const end = commitment.end ? new Date(commitment.end) : null;
  const rate = commitment.run_rate ?? 0;
  const horizonEnd = end ?? new Date(today.getFullYear() + 1, today.getMonth(), 1);
  const origin = start ?? new Date(today.getFullYear(), today.getMonth() - 6, 1);
  const span = Math.max(horizonEnd.getTime() - origin.getTime(), 1);
  const monthsToEnd = Math.max((horizonEnd.getTime() - today.getTime()) / (30.4375 * 864e5), 0);
  const projectedAtEnd = commitment.consumed + rate * monthsToEnd;
  const maximum = niceCeiling(Math.max(commitment.original, projectedAtEnd));
  const xOf = (day: Date) => PLOT_LEFT + ((day.getTime() - origin.getTime()) / span) * (WIDTH - PLOT_LEFT - PLOT_RIGHT);
  const yOf = (value: number) => PLOT_TOP + plotHeight - (value / maximum) * plotHeight;
  const currency = commitment.currency;

  return (
    <>
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="azure-cost-chart" role="img"
           aria-label="Commitment consumed and projected">
        <YAxis maximum={maximum} plotHeight={plotHeight} currency={currency} />
        <line x1={PLOT_LEFT} x2={WIDTH - PLOT_RIGHT} y1={yOf(commitment.original)} y2={yOf(commitment.original)}
              className="azure-cost-commitment-line" />
        <text x={WIDTH - PLOT_RIGHT} y={yOf(commitment.original) - 6} textAnchor="end" className="azure-cost-axis-label">
          Commitment {formatMoney(commitment.original, currency, true)}
        </text>
        {start ? (
          <line x1={xOf(start)} y1={yOf(0)} x2={xOf(today)} y2={yOf(commitment.consumed)} className="azure-cost-line" />
        ) : null}
        <line x1={xOf(today)} y1={yOf(commitment.consumed)} x2={xOf(horizonEnd)} y2={yOf(projectedAtEnd)}
              className="azure-cost-projection" />
        <circle cx={xOf(today)} cy={yOf(commitment.consumed)} r={4} className="azure-cost-line-point" />
        <line x1={xOf(today)} x2={xOf(today)} y1={PLOT_TOP} y2={PLOT_TOP + plotHeight} className="azure-cost-today" />
        <text x={xOf(today)} y={height - 8} textAnchor="middle" className="azure-cost-axis-label">Today</text>
        {start ? <text x={xOf(start)} y={height - 8} textAnchor="start" className="azure-cost-axis-label">{commitment.start}</text> : null}
        {end ? <text x={xOf(end)} y={height - 8} textAnchor="end" className="azure-cost-axis-label">Term end {commitment.end}</text> : null}
      </svg>
      <Legend items={[
        { label: 'Consumed', color: 'var(--azure-cost-series-2)' },
        { label: 'Projected at run rate', color: 'var(--azure-cost-series-2)', dashed: true },
        { label: 'Commitment', color: 'var(--color-text-muted)', dashed: true },
      ]} />
    </>
  );
}

/** Consumed share of the commitment as one bar. */
export function CommitmentGauge({ commitment }: { commitment: Commitment }) {
  const pct = Math.min(Math.max(commitment.consumed_pct ?? 0, 0), 100);
  return (
    <div className="azure-cost-gauge" title={`${pct}% consumed`}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}
