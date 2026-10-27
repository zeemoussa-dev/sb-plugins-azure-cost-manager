// `esm/`, not `lib/`: lib/core is CommonJS, and the Vite dev server hands its
// default import over as the module object, which React refuses to render.
import ReactEChartsCore from 'echarts-for-react/esm/core';
import { BarChart, LineChart, PieChart } from 'echarts/charts';
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import type { ReactNode } from 'react';
import type { BreakdownRow, BurnDown, ConsumptionRow, ForecastMonth, MixGroup, MonthTotal } from './client';
import { formatMoney, formatMonth } from './format';

// The host provides echarts (framework_api 8); importing `echarts/core` plus the
// pieces drawn here keeps the rest of the library out of the app's bundle.
echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent,
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

/** `onPick(category, series)`: a bar, point or axis label clicked -- what drill-downs
 *  open from (operator, 2026-10-23: "every graph can be drilled down"). */
export type Pick = (category: string, series: string) => void;

interface ClickParams { componentType?: string; name?: string; seriesName?: string; value?: unknown }

function Chart({ option, height = 280, label, onPick }: { option: object; height?: number; label: string; onPick?: Pick }) {
  const events = onPick ? {
    click: (params: ClickParams) => {
      if (params.componentType === 'xAxis') onPick(String(params.value ?? ''), '');
      else if (params.name) onPick(params.name, params.seriesName ?? '');
    },
  } : undefined;
  const picked = onPick ? withPointer(option as Record<string, unknown>) : option;
  return (
    <div role="img" aria-label={label} className={onPick ? 'azure-cost-pickable' : undefined}>
      <ReactEChartsCore echarts={echarts} option={picked} notMerge onEvents={events} style={{ height, width: '100%' }} />
    </div>
  );
}

/** A clickable chart shows it: a pointer over bars and points, and axis labels that answer a click. */
function withPointer(option: Record<string, unknown>): Record<string, unknown> {
  const axis = option.xAxis as Record<string, unknown> | undefined;
  const series = (option.series as Record<string, unknown>[] | undefined) ?? [];
  return { ...option, ...(axis ? { xAxis: { ...axis, triggerEvent: true } } : {}),
    series: series.map((item) => ({ ...item, cursor: 'pointer' })) };
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

export interface Series {
  name: string;
  data: (number | null)[];
  kind?: 'bar' | 'line';
  stack?: string;
  dashed?: boolean;
  /** 'other' draws it grey; a number picks a palette slot. */
  color?: number | 'other';
}

/** Any chart of the workbook's kind: categories along the bottom, bars and lines
 *  over them, money or percent up the side. */
export function SeriesChart({ categories, series, currency, label, percent = false, height = 280,
  categoryLabel = (value: string) => value, onPick }: {
  categories: string[]; series: Series[]; currency: string | null; label: string; percent?: boolean;
  height?: number; categoryLabel?: (value: string) => string; onPick?: Pick;
}) {
  const { colors, option } = baseOption(currency);
  const value = (amount: number) => (percent ? `${amount > 0 ? '+' : ''}${amount}%` : formatMoney(amount, currency));
  return (
    <Chart label={label} height={height} onPick={onPick} option={{
      ...option,
      color: series.map((item, index) => item.color === 'other' ? colors.other
        : colors.series[(typeof item.color === 'number' ? item.color : index) % colors.series.length]),
      legend: { ...option.legend, type: 'scroll', right: 0 },
      grid: { ...option.grid, top: series.length > 1 ? 44 : 16 },
      tooltip: { ...option.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (items: AxisTooltipItem[]) => {
          const shown = items.filter((item) => item.value != null);
          if (!shown.length) return '';
          return [`<b>${categoryLabel(shown[0].axisValue)}</b>`,
            ...shown.map((item) => `${item.marker}${item.seriesName}: <b>${value(item.value ?? 0)}</b>`)].join('<br/>');
        } },
      xAxis: { type: 'category', data: categories, axisLabel: { color: colors.muted, formatter: categoryLabel },
        axisLine: { lineStyle: { color: colors.border } } },
      yAxis: percent
        ? { ...option.yAxis, axisLabel: { color: colors.muted, formatter: (amount: number) => `${amount}%` } }
        : option.yAxis,
      series: series.map((item) => ({
        name: item.name, type: item.kind ?? 'bar', data: item.data, stack: item.stack, barMaxWidth: 36,
        symbolSize: 5, connectNulls: false, emphasis: { focus: 'series' },
        lineStyle: item.dashed ? { type: 'dashed', width: 2 } : { width: 2 },
        ...(item.dashed && item.kind !== 'line'
          ? { itemStyle: { color: 'transparent', borderColor: colors.series[0], borderType: 'dashed', borderWidth: 1.5 } }
          : {}),
      })),
    }} />
  );
}

export interface Move {
  name: string;
  change: number;
}

/** Drops and increases as bars: green up, red down, the largest of each (operator,
 *  2026-10-27: "red means drop and green means increase", everywhere a change is shown).
 *  `percent`: the changes are percentages, not money. */
export function ChangeBars({ rows, currency, label, percent = false, most = 8, onPick }: {
  rows: Move[]; currency: string | null; label: string; percent?: boolean; most?: number; onPick?: (name: string) => void;
}) {
  const { colors, option } = baseOption(currency);
  const up = rows.filter((row) => row.change > 0).sort((a, b) => b.change - a.change).slice(0, most);
  const down = rows.filter((row) => row.change < 0).sort((a, b) => a.change - b.change).slice(0, most);
  if (!up.length && !down.length) return <p className="text-muted">Nothing moved.</p>;
  // Largest increase on top, largest drop at the bottom.
  const shown = [...up, ...down.reverse()].reverse();
  const green = cssColor('--color-success', '#3fb950');
  const red = cssColor('--color-danger', '#e5534b');
  const value = (amount: number) => (percent ? `${amount > 0 ? '+' : ''}${amount}%`
    : `${amount > 0 ? '+' : '−'}${formatMoney(Math.abs(amount), currency, true)}`);
  return (
    <Chart label={label} height={Math.max(160, shown.length * 26 + 40)}
           onPick={onPick ? (name) => onPick(name) : undefined} option={{
      ...option,
      grid: { ...option.grid, top: 8, left: 8, right: 56 },
      tooltip: { ...option.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (items: { name: string; value: number }[]) => `<b>${items[0].name}</b><br/>${value(items[0].value)}` },
      xAxis: { type: 'value', axisLabel: { color: colors.muted, formatter: (amount: number) => percent ? `${amount}%`
        : formatMoney(amount, currency, true) }, splitLine: { lineStyle: { color: colors.border } } },
      yAxis: { type: 'category', data: shown.map((row) => row.name),
        axisLabel: { color: colors.muted, width: 180, overflow: 'truncate' }, axisLine: { lineStyle: { color: colors.border } } },
      series: [{
        type: 'bar', barMaxWidth: 18,
        data: shown.map((row) => ({ value: row.change, itemStyle: { color: row.change >= 0 ? green : red } })),
        label: { show: true, position: 'right', color: colors.muted, fontSize: 11,
          formatter: (item: { value: number }) => value(item.value) },
      }],
    }} />
  );
}

export interface Slice {
  name: string;
  value: number;
}

/** Shares of one whole: the largest `most` slices, the rest as "Others" so a group of
 *  49 affiliates still reads (operator, 2026-10-25: the allocation "makes more sense" as a pie). */
export function SharesPie({ slices, currency, label, height = 280, most = 8 }: {
  slices: Slice[]; currency: string | null; label: string; height?: number; most?: number;
}) {
  const { colors, option } = baseOption(currency);
  const sorted = slices.filter((slice) => slice.value > 0).sort((a, b) => b.value - a.value);
  const rest = sorted.slice(most).reduce((sum, slice) => sum + slice.value, 0);
  const shown = [...sorted.slice(0, most), ...(rest > 0 ? [{ name: `Others (${sorted.length - most})`, value: rest }] : [])];
  const total = shown.reduce((sum, slice) => sum + slice.value, 0);
  return (
    <div>
    <h4 className="azure-cost-pie-title">{label}</h4>
    <Chart label={label} height={height} option={{
      backgroundColor: option.backgroundColor, textStyle: option.textStyle,
      color: shown.map((_slice, index) => (rest > 0 && index === shown.length - 1 ? colors.other
        : colors.series[index % colors.series.length])),
      legend: { type: 'scroll', bottom: 0, left: 'center', textStyle: { color: colors.muted }, icon: 'circle',
        itemWidth: 8, itemHeight: 8 },
      tooltip: { ...option.tooltip, trigger: 'item',
        formatter: (item: { marker: string; name: string; value: number }) =>
          `${item.marker}${item.name}: <b>${formatMoney(item.value, currency)}</b> (${total ? Math.round((item.value / total) * 1000) / 10 : 0}%)` },
      series: [{
        type: 'pie', radius: ['38%', '66%'], center: ['50%', '50%'], data: shown, avoidLabelOverlap: true,
        itemStyle: { borderColor: colors.surface, borderWidth: 2 },
        label: { color: colors.muted, formatter: (item: { percent: number }) => `${Math.round(item.percent)}%` },
      }],
    }} />
    </div>
  );
}

/** Monthly spend: actual as bars, amortized as a line, the rest of the year's
 *  forecast as outlined bars. The current month's bar is drawn lighter: it is
 *  still being billed. */
export function TrendChart({ months, forecast, currency, onPick }: {
  months: MonthTotal[]; forecast: ForecastMonth[]; currency: string | null; onPick?: Pick;
}) {
  const { colors, option } = baseOption(currency);
  const categories = [...new Set([...months.map((month) => month.month), ...forecast.map((month) => month.month)])].sort();
  const actualByMonth = new Map(months.map((month) => [month.month, month]));
  const forecastByMonth = new Map(forecast.map((month) => [month.month, month]));

  return (
    <Chart label="Monthly spend, actual and amortized, with forecast" onPick={onPick} option={{
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

/** Each month split into the biggest series plus "Other", to see the mix move.
 *  By enrollment it shows a renewal as one colour handing over to another. */
export function StackedMonthsChart({ rows, groupKey, currency, series = 6, onPick }: {
  rows: ConsumptionRow[]; groupKey: MixGroup; currency: string | null; series?: number; onPick?: Pick;
}) {
  if (!rows.length) return <p className="text-muted">No consumption synced yet.</p>;
  const { colors, option } = baseOption(currency);
  const totalsByName = new Map<string, number>();
  for (const row of rows) totalsByName.set(row.name, (totalsByName.get(row.name) ?? 0) + row.cost);
  const named = [...totalsByName.entries()].sort((a, b) => b[1] - a[1]).slice(0, series).map(([name]) => name);
  const months = [...new Set(rows.map((row) => row.month))].sort();
  const valueOf = (month: string, key: string) => rows
    .filter((row) => row.month === month)
    .filter((row) => key === 'Other' ? !named.includes(row.name) : row.name === key)
    .reduce((sum, row) => sum + row.cost, 0);
  const keys = [...named, ...(totalsByName.size > named.length ? ['Other'] : [])];

  return (
    <Chart label={`Monthly spend by ${groupKey}`} height={320} onPick={onPick} option={{
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
export function RankedBars({ rows, currency, onPick, renderName }: {
  rows: BreakdownRow[]; currency: string | null; onPick?: (name: string) => void;
  /** How a row's name is shown, when it is more than text. */
  renderName?: (name: string) => ReactNode;
}) {
  const maximum = Math.max(...rows.map((row) => row.cost), 1);
  return (
    <div className="azure-cost-ranked">
      {rows.map((row) => (
        <div key={row.name} className={`azure-cost-ranked-row${onPick ? ' azure-cost-pickable' : ''}`}
             title={`${row.name}: ${formatMoney(row.cost, currency)}`}
             role={onPick ? 'button' : undefined} tabIndex={onPick ? 0 : undefined}
             onClick={onPick ? () => onPick(row.name) : undefined}
             onKeyDown={onPick ? (event) => { if (event.key === 'Enter') onPick(row.name); } : undefined}>
          <span className="azure-cost-ranked-name">{renderName ? renderName(row.name) : row.name}</span>
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

function endOfMonth(month: string): number {
  const [year, number] = month.split('-').map(Number);
  return Date.UTC(year, number, 0);
}

/** Consumption since the term began, month by month, against what the customer
 *  signed: the even pace that would land exactly on it, and where the run rate
 *  takes consumption by the end of the term. */
export function BurnDownChart({ commitment, today }: { commitment: BurnDown; today: Date }) {
  const currency = commitment.currency;
  const { colors, option } = baseOption(currency);
  const start = Date.parse(commitment.start);
  const end = Date.parse(commitment.end);
  const consumed = [[start, 0], ...commitment.cumulative.map((point) =>
    [point.partial ? today.getTime() : endOfMonth(point.month), point.consumed])];
  const projection = commitment.run_rate
    ? [[today.getTime(), commitment.consumed], [end, Math.round(commitment.projected_at_end)]]
    : [];

  return (
    <Chart label="Consumption against the signed value" height={300} option={{
      ...option,
      color: [colors.series[1], colors.series[1], colors.muted],
      tooltip: { ...option.tooltip, trigger: 'item',
        formatter: (item: { seriesName: string; value: [number, number] }) =>
          `${item.seriesName}<br/>${new Date(item.value[0]).toISOString().slice(0, 10)}: <b>${formatMoney(item.value[1], currency)}</b>` },
      xAxis: { type: 'time', min: start, max: end, axisLabel: { color: colors.muted },
        axisLine: { lineStyle: { color: colors.border } }, splitLine: { show: false } },
      yAxis: { ...option.yAxis, max: (value: { max: number }) => Math.max(value.max, commitment.amount) * 1.05 },
      series: [
        { name: 'Consumed', type: 'line', data: consumed, symbolSize: 5, lineStyle: { width: 2.5 },
          areaStyle: { opacity: 0.12 },
          markLine: { silent: true, symbol: 'none', label: { color: colors.muted },
            lineStyle: { color: colors.muted, type: 'dashed' },
            data: [
              { yAxis: commitment.amount, label: { formatter: `Signed ${formatMoney(commitment.amount, currency, true)}`, position: 'insideEndTop' } },
              { xAxis: today.getTime(), label: { formatter: 'Today', position: 'end' } },
            ] } },
        { name: 'Projected at run rate', type: 'line', data: projection, symbolSize: 5,
          lineStyle: { width: 2, type: 'dashed' } },
        { name: 'Even pace', type: 'line', data: [[start, 0], [end, commitment.amount]], symbol: 'none',
          lineStyle: { width: 1, type: 'dotted' } },
        ...(commitment.pipeline_in_term > 0 && commitment.run_rate ? [{
          name: 'Run rate + pipeline', type: 'line', symbolSize: 5,
          data: [[today.getTime(), commitment.consumed], [end, Math.round(commitment.projected_with_pipeline)]],
          lineStyle: { width: 2, type: 'dashed' }, itemStyle: { color: colors.series[2] },
        }] : []),
      ],
    }} />
  );
}

/** Consumed share of the commitment as one bar, with where an even pace would be. */
export function CommitmentGauge({ commitment }: { commitment: BurnDown }) {
  const pct = Math.min(Math.max(commitment.consumed_pct, 0), 100);
  const pace = Math.min(Math.max(commitment.elapsed_pct, 0), 100);
  return (
    <div className="azure-cost-gauge" title={`${pct}% consumed, ${pace}% of the term elapsed`}>
      <span style={{ width: `${pct}%` }} />
      <i style={{ left: `${pace}%` }} />
    </div>
  );
}
