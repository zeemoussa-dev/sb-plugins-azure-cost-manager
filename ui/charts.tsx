// `esm/`, not `lib/`: lib/core is CommonJS, and the Vite dev server hands its
// default import over as the module object, which React refuses to render.
import ReactEChartsCore from 'echarts-for-react/esm/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import type { ReactNode } from 'react';
import type { BreakdownRow, Commitment, ConsumptionRow, ForecastMonth, MonthTotal } from './client';
import { formatMoney, formatMonth } from './format';

// The host provides echarts (framework_api 8); importing `echarts/core` plus the
// pieces drawn here keeps the rest of the library out of the app's bundle.
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent,
  CanvasRenderer]);

const SERIES_VARIABLES = [
  '--azure-cost-series-1', '--azure-cost-series-2', '--azure-cost-series-3', '--azure-cost-series-4',
  '--azure-cost-series-5', '--azure-cost-series-6',
];
const OTHER_VARIABLE = '--azure-cost-series-other';

/** A canvas cannot resolve `var(--x)`, so colours are read from the stylesheet
 *  at render time: the charts stay on the same palette as the rest of the page. */
function cssColor(variable: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(variable).trim();
  return value || fallback;
}

function palette() {
  return {
    series: SERIES_VARIABLES.map((variable) => cssColor(variable, '#4c9be8')),
    other: cssColor(OTHER_VARIABLE, '#6b7280'),
    text: cssColor('--color-text', '#e9e4d6'),
    muted: cssColor('--color-text-muted', '#b9b4a6'),
    border: cssColor('--color-border', 'rgba(233, 228, 214, 0.1)'),
    surface: cssColor('--color-surface-raised', '#1f2430'),
  };
}

function baseOption(currency: string | null) {
  const colors = palette();
  return {
    colors,
    option: {
      backgroundColor: 'transparent',
      textStyle: { color: colors.muted, fontFamily: 'inherit' },
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, textStyle: { color: colors.muted }, icon: 'roundRect', itemWidth: 12, itemHeight: 8 },
      tooltip: {
        backgroundColor: colors.surface,
        borderColor: colors.border,
        textStyle: { color: colors.text, fontSize: 12 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: colors.muted, formatter: (value: number) => formatMoney(value, currency, true) },
        splitLine: { lineStyle: { color: colors.border } },
      },
    },
  };
}

function Chart({ option, height = 280, label }: { option: object; height?: number; label: string }) {
  return (
    <div role="img" aria-label={label}>
      <ReactEChartsCore echarts={echarts} option={option} notMerge style={{ height, width: '100%' }} />
    </div>
  );
}

interface AxisTooltipItem {
  axisValue: string;
  seriesName: string;
  value: number | null;
  marker: string;
}

function axisTooltip(currency: string | null, title: (axisValue: string) => string) {
  return (items: AxisTooltipItem[]) => {
    const shown = items.filter((item) => item.value != null && item.value !== 0);
    if (!shown.length) return '';
    return [title(shown[0].axisValue),
      ...shown.map((item) => `${item.marker}${item.seriesName}: <b>${formatMoney(item.value ?? 0, currency)}</b>`)]
      .join('<br/>');
  };
}

/** Monthly spend: actual as bars, amortized as a line, the rest of the year's
 *  forecast as outlined bars. The current month's bar is drawn lighter: it is
 *  still being billed. */
export function TrendChart({ months, forecast, currency }: {
  months: MonthTotal[]; forecast: ForecastMonth[]; currency: string | null;
}) {
  const { colors, option } = baseOption(currency);
  const categories = [...new Set([...months.map((month) => month.month), ...forecast.map((month) => month.month)])].sort();
  const actualByMonth = new Map(months.map((month) => [month.month, month]));
  const forecastByMonth = new Map(forecast.map((month) => [month.month, month]));

  return (
    <Chart label="Monthly spend, actual and amortized, with forecast" option={{
      ...option,
      color: [colors.series[0], colors.series[1], colors.series[0]],
      tooltip: { ...option.tooltip, trigger: 'axis', formatter: axisTooltip(currency, (month) => {
        const partial = actualByMonth.get(month)?.partial ? ' (so far)' : '';
        const mom = actualByMonth.get(month)?.mom_pct;
        return `<b>${formatMonth(month)}</b>${partial}${mom != null ? ` · ${mom > 0 ? '+' : ''}${mom}% vs previous` : ''}`;
      }) },
      xAxis: { type: 'category', data: categories, axisLabel: { color: colors.muted, formatter: (month: string) => formatMonth(month, true) },
        axisLine: { lineStyle: { color: colors.border } } },
      series: [
        { name: 'Actual', type: 'bar', barMaxWidth: 36,
          data: categories.map((month) => {
            const actual = actualByMonth.get(month);
            if (!actual) return null;
            return actual.partial ? { value: actual.actual, itemStyle: { opacity: 0.45 } } : actual.actual;
          }) },
        { name: 'Amortized', type: 'line', symbolSize: 6, smooth: false,
          data: categories.map((month) => actualByMonth.get(month)?.amortized ?? null) },
        // Drawn over the actual bar's slot, so the current month shows billed-so-far inside its projection.
        { name: 'Forecast', type: 'bar', barMaxWidth: 36, barGap: '-100%', z: 1,
          itemStyle: { color: 'transparent', borderColor: colors.series[0], borderType: 'dashed', borderWidth: 1.5 },
          data: categories.map((month) => forecastByMonth.get(month)?.cost ?? null) },
      ],
    }} />
  );
}

/** Each month split into the biggest series plus "Other", to see the mix move. */
export function StackedMonthsChart({ rows, groupKey, currency, series = 6 }: {
  rows: ConsumptionRow[]; groupKey: 'service' | 'subscription'; currency: string | null; series?: number;
}) {
  if (!rows.length) return <p className="text-muted">No consumption cached yet.</p>;
  const { colors, option } = baseOption(currency);
  const totalsByName = new Map<string, number>();
  for (const row of rows) {
    const name = row[groupKey] ?? 'Unassigned';
    totalsByName.set(name, (totalsByName.get(name) ?? 0) + row.cost);
  }
  const named = [...totalsByName.entries()].sort((a, b) => b[1] - a[1]).slice(0, series).map(([name]) => name);
  const months = [...new Set(rows.map((row) => row.month))].sort();
  const valueOf = (month: string, key: string) => rows
    .filter((row) => row.month === month)
    .filter((row) => {
      const name = row[groupKey] ?? 'Unassigned';
      return key === 'Other' ? !named.includes(name) : name === key;
    })
    .reduce((sum, row) => sum + row.cost, 0);
  const keys = [...named, ...(totalsByName.size > named.length ? ['Other'] : [])];

  return (
    <Chart label={`Monthly spend by ${groupKey}`} height={320} option={{
      ...option,
      color: keys.map((key, index) => key === 'Other' ? colors.other : colors.series[index % colors.series.length]),
      legend: { ...option.legend, type: 'scroll', right: 0 },
      grid: { ...option.grid, top: 44 },
      tooltip: { ...option.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: axisTooltip(currency, (month) => `<b>${formatMonth(month)}</b>`) },
      xAxis: { type: 'category', data: months, axisLabel: { color: colors.muted, formatter: (month: string) => formatMonth(month, true) },
        axisLine: { lineStyle: { color: colors.border } } },
      series: keys.map((key) => ({
        name: key, type: 'bar', stack: 'spend', barMaxWidth: 36, emphasis: { focus: 'series' },
        data: months.map((month) => Math.round(valueOf(month, key) * 100) / 100),
      })),
    }} />
  );
}

/** Ranked rows with each one's share and change against last month. A table
 *  more than a chart: the share and the change are what is read. */
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

const DAY_MS = 864e5;

/** The commitment: consumed so far against the whole, and where the run rate
 *  takes it -- a straight projection from today, with the term's end marked. */
export function BurnDownChart({ commitment, today }: { commitment: Commitment; today: Date }) {
  const currency = commitment.currency;
  const { colors, option } = baseOption(currency);
  const start = commitment.start ? new Date(commitment.start) : null;
  const end = commitment.end ? new Date(commitment.end) : null;
  const horizonEnd = end ?? new Date(today.getFullYear() + 1, today.getMonth(), 1);
  const monthsToEnd = Math.max((horizonEnd.getTime() - today.getTime()) / (30.4375 * DAY_MS), 0);
  const projectedAtEnd = commitment.consumed + (commitment.run_rate ?? 0) * monthsToEnd;
  const consumedLine = [...(start ? [[start.getTime(), 0]] : []), [today.getTime(), commitment.consumed]];
  const projectionLine = commitment.run_rate
    ? [[today.getTime(), commitment.consumed], [horizonEnd.getTime(), Math.round(projectedAtEnd)]]
    : [];

  return (
    <Chart label="Commitment consumed and projected" height={260} option={{
      ...option,
      color: [colors.series[1], colors.series[1]],
      tooltip: { ...option.tooltip, trigger: 'item',
        formatter: (item: { seriesName: string; value: [number, number] }) =>
          `${item.seriesName}<br/>${new Date(item.value[0]).toISOString().slice(0, 10)}: <b>${formatMoney(item.value[1], currency)}</b>` },
      xAxis: { type: 'time', min: (start ?? new Date(today.getTime() - 180 * DAY_MS)).getTime(), max: horizonEnd.getTime(),
        axisLabel: { color: colors.muted }, axisLine: { lineStyle: { color: colors.border } }, splitLine: { show: false } },
      yAxis: { ...option.yAxis, max: (value: { max: number }) => Math.max(value.max, commitment.original) * 1.05 },
      series: [
        { name: 'Consumed', type: 'line', data: consumedLine, symbolSize: 7, lineStyle: { width: 2 },
          markLine: { silent: true, symbol: 'none', label: { color: colors.muted },
            lineStyle: { color: colors.muted, type: 'dashed' },
            data: [
              { yAxis: commitment.original, label: { formatter: `Commitment ${formatMoney(commitment.original, currency, true)}`, position: 'insideEndTop' } },
              { xAxis: today.getTime(), label: { formatter: 'Today', position: 'end' } },
            ] } },
        { name: 'Projected at run rate', type: 'line', data: projectionLine, symbolSize: 5,
          lineStyle: { width: 2, type: 'dashed' } },
      ],
    }} />
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
