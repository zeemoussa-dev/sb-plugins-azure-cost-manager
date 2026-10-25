import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router';
import { BurnDownChart, Change, CommitmentGauge, SeriesChart, TrendChart } from './charts';
import type { Analysis } from './client';
import { useRememberedFold } from './CompassText';
import { useDrillOpener } from './Drill';
import { formatMoney, formatMonth } from './format';
import { settingsLink } from './ReportsHome';
import { SolutionPlaysCard } from './SolutionPlays';

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function Kpi({ label, value, detail, warn }: { label: string; value: ReactNode; detail?: ReactNode; warn?: boolean }) {
  return (
    <div className="azure-cost-kpi card">
      <span className="azure-cost-kpi-label">{label}</span>
      <strong className={warn ? 'azure-cost-warning' : undefined}>{value}</strong>
      {detail ? <span className="azure-cost-kpi-detail">{detail}</span> : null}
    </div>
  );
}

const money = (value: number | null | undefined, currency: string | null) =>
  value == null ? '—' : formatMoney(value, currency);
const percent = (value: number | null | undefined) => value == null ? '—' : `${value > 0 ? '+' : ''}${value}%`;

function Kpis({ analysis }: { analysis: Analysis }) {
  const kpis = analysis.dashboard.kpis;
  const currency = analysis.currency;
  const commitment = analysis.commitment;
  return (
    <div className="azure-cost-kpis">
      <Kpi label="Total, all synced months" value={money(kpis.all_time, currency)}
           detail={`${kpis.months_of_history} months from ${kpis.first_month ? formatMonth(kpis.first_month) : '—'}`} />
      <Kpi label={`YTD through ${kpis.ytd_through ? formatMonth(kpis.ytd_through) : '—'}`} value={money(kpis.ytd, currency)}
           detail={kpis.ytd_growth_pct != null ? <><Change pct={kpis.ytd_growth_pct} /> on last year</> : null} />
      <Kpi label={`Latest month${kpis.latest_month ? ` (${formatMonth(kpis.latest_month)})` : ''}`}
           value={money(kpis.latest_total, currency)}
           detail={<>MoM {percent(kpis.latest_mom_pct)} · YoY {percent(kpis.latest_yoy_pct)}</>} />
      <Kpi label={kpis.current_month ? `${formatMonth(kpis.current_month)} so far` : 'This month so far'}
           value={money(kpis.current_so_far, currency)} />
      <Kpi label="Next 12 months (auto forecast)" value={money(kpis.next_12_months, currency)}
           detail={analysis.automatic_forecast
             ? `${formatMoney(analysis.automatic_forecast.next_12_months_with_pipeline, currency)} with pipeline` : null} />
      <Kpi label={`${analysis.automatic_forecast?.next_year ?? ''} forecast (auto)`} value={money(kpis.next_year_forecast, currency)}
           detail={analysis.automatic_forecast?.next_vs_this_pct != null
             ? `${percent(analysis.automatic_forecast.next_vs_this_pct)} on this year` : null} />
      <Kpi label="Consumption rate, 3-month average" value={money(kpis.burn_rate_3m, currency)} />
      <Kpi label="Active enrollments" value={kpis.active_enrollments}
           detail={kpis.largest_enrollment_share_pct != null ? `largest carries ${kpis.largest_enrollment_share_pct}%` : null} />
      {commitment ? (
        <>
          <Kpi label={`Signed (${commitment.type})`} value={money(commitment.amount, commitment.currency)}
               detail={`${commitment.start} → ${commitment.end}`} />
          <Kpi label="Consumed against it" value={`${commitment.consumed_pct}%`}
               detail={`${commitment.elapsed_pct}% of the term elapsed`} warn={commitment.pace_gap < 0} />
          <Kpi label="Remaining" value={money(commitment.remaining, commitment.currency)}
               detail={kpis.runway_months != null ? `${kpis.runway_months} months at the current consumption rate` : null} />
          <Kpi label="Projected exhaustion"
               value={commitment.projected_exhaustion ? formatMonth(commitment.projected_exhaustion) : 'not within term'}
               warn={!commitment.projected_exhaustion} />
        </>
      ) : null}
      {kpis.credits_all_time ? (
        <Kpi label="Credits applied" value={money(kpis.credits_all_time, currency)}
             detail={analysis.measure.credits ? 'subtracted from totals' : 'not subtracted'} />
      ) : null}
      {kpis.marketplace_all_time ? (
        <Kpi label="Marketplace" value={money(kpis.marketplace_all_time, currency)}
             detail={analysis.measure.marketplace === 'core42'
               ? `only Core42's ${money(kpis.core42_marketplace_all_time ?? 0, currency)} in totals`
               : analysis.measure.marketplace ? 'included in totals' : 'excluded from totals'} />
      ) : null}
      {kpis.core42_revenue_all_time != null ? (
        <Kpi label="Core42 revenue" value={money(kpis.core42_revenue_all_time, currency)}
             detail={`${money(kpis.core42_revenue_this_year ?? 0, currency)} this year · without other publishers' Marketplace${
               analysis.measure.credits ? ', less credits' : ''}`} />
      ) : null}
    </div>
  );
}

function CommitmentCard({ analysis }: { analysis: Analysis }) {
  const location = useLocation();
  const commitment = analysis.commitment;
  const parent = analysis.group.parent;
  if (!commitment && parent?.rolls_up) {
    return (
      <section className="card azure-cost-card">
        <h3>Signed value</h3>
        <p className="text-muted">
          {analysis.customer.name} signs no MACC of its own: its consumption counts toward{' '}
          <Link to={`?report=Overview&customer=${encodeURIComponent(parent.id)}`}>{parent.name}'s MACC</Link>
          {parent.amount != null ? ` (${formatMoney(parent.amount, parent.currency)})` : ''}.
        </p>
      </section>
    );
  }
  if (!commitment) {
    return (
      <section className="card azure-cost-card">
        <h3>Signed value</h3>
        <p className="text-muted">
          No signed value entered for this customer. Azure does not report it for indirect agreements —{' '}
          <Link to={settingsLink({ location, label: analysis.customer.name }, analysis.customer.id)}>enter it in Settings</Link>.
        </p>
      </section>
    );
  }
  const currency = commitment.currency;
  return (
    <section className="card azure-cost-card">
      <h3>Consumption against the signed value</h3>
      <CommitmentGauge commitment={commitment} />
      <dl className="azure-cost-facts">
        <dt>Signed</dt><dd>{formatMoney(commitment.amount, currency)} ({commitment.type})</dd>
        <dt>Counts</dt>
        <dd>Usage and all Marketplace (except offers marked as not eligible), less credits
          {analysis.group.affiliates.length
            ? commitment.affiliates === 'own'
              ? ` — this customer's own enrollments only: each affiliate signed its own MACC (totals above include them)`
              : ` — including its ${analysis.group.affiliates.length} affiliate(s)`
            : ''}</dd>
        <dt>Consumed</dt><dd>{formatMoney(commitment.consumed, currency)} ({commitment.consumed_pct}%)</dd>
        <dt>Against an even pace</dt>
        <dd className={commitment.pace_gap < 0 ? 'azure-cost-warning' : undefined}>
          {commitment.pace_gap >= 0 ? 'ahead by ' : 'behind by '}{formatMoney(Math.abs(commitment.pace_gap), currency)}
        </dd>
        <dt>At term end, at run rate</dt><dd>{formatMoney(commitment.projected_at_end, currency)}</dd>
        {commitment.pipeline_in_term ? (
          <><dt>…with the pipeline</dt>
            <dd>{formatMoney(commitment.projected_with_pipeline, currency)}
              {commitment.shortfall_with_pipeline
                ? <span className="azure-cost-warning"> (still short {formatMoney(commitment.shortfall_with_pipeline, currency)})</span>
                : ' (covers the commitment)'}</dd></>
        ) : null}
        {commitment.projected_shortfall ? (
          <><dt>Shortfall at run rate</dt><dd className="azure-cost-warning">{formatMoney(commitment.projected_shortfall, currency)}</dd></>
        ) : null}
      </dl>
      <p className="azure-cost-verdict">{commitment.verdict}</p>
      <BurnDownChart commitment={commitment} today={new Date()} />
    </section>
  );
}

/** How the parent's MACC is carved up: each affiliate's own MACC and its burn,
 *  and the unallocated rest, which the parent's own enrollments consume. */
function AllocationsCard({ analysis }: { analysis: Analysis }) {
  const [open, fold] = useRememberedFold('azure-cost-manager.allocations-folded', true);
  const allocations = analysis.allocations;
  if (!allocations) return null;
  const currency = analysis.commitment?.currency ?? analysis.currency;
  const pct = (value: number, of: number | null | undefined) => (of ? `${Math.round((value / of) * 1000) / 10}%` : '—');
  const rows = allocations.affiliates;
  return (
    <details className="card azure-cost-card azure-cost-wide azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head">
        <h3>MACC allocation across the group</h3>
        {!open ? <span className="text-muted">{rows.length} affiliate{rows.length === 1 ? '' : 's'}</span> : null}
      </summary>
      {allocations.parent_amount == null ? (
        <p className="text-muted azure-cost-note">Enter the group's signed MACC on this customer to see what is left unallocated.</p>
      ) : null}
      {allocations.over_allocated ? (
        <div className="azure-cost-error">
          The affiliates' MACCs add up to {formatMoney(allocations.allocated, currency)}, more than the group's{' '}
          {formatMoney(allocations.parent_amount ?? 0, currency)}.
        </div>
      ) : null}
      <table className="azure-cost-table">
        <thead><tr><th>Affiliate</th><th>Signed MACC</th><th>Consumed</th><th>%</th><th>Remaining</th>
          <th>Against even pace</th><th>At term end (run rate)</th><th /></tr></thead>
        <tbody>
          {rows.map((row) => {
            const burn = row.burn;
            return (
              <tr key={row.id}>
                <td>{row.name}</td>
                <td>{row.commitment ? formatMoney(row.commitment.amount, currency) : <span className="text-muted">not entered</span>}</td>
                <td>{formatMoney(burn ? burn.consumed : row.consumed_against_parent, currency)}</td>
                <td>{burn ? `${burn.consumed_pct}%` : '—'}</td>
                <td>{burn ? formatMoney(burn.remaining, currency) : '—'}</td>
                <td className={burn && burn.pace_gap < 0 ? 'azure-cost-warning' : undefined}>
                  {burn ? `${burn.pace_gap >= 0 ? 'ahead ' : 'behind '}${formatMoney(Math.abs(burn.pace_gap), currency)}` : '—'}</td>
                <td>{burn ? formatMoney(burn.projected_at_end, currency) : '—'}</td>
                <td className="text-muted">{burn?.projected_shortfall ? 'shortfall projected' : burn ? 'on track' : ''}</td>
              </tr>
            );
          })}
          <tr>
            <td>{analysis.customer.name} — unallocated, own enrollments</td>
            <td>{allocations.unallocated != null ? formatMoney(allocations.unallocated, currency) : '—'}</td>
            <td>{formatMoney(allocations.own.consumed, currency)}</td>
            <td>{pct(allocations.own.consumed, allocations.unallocated)}</td>
            <td>{allocations.own.remaining != null ? formatMoney(allocations.own.remaining, currency) : '—'}</td>
            <td /><td /><td />
          </tr>
          <tr className="azure-cost-total-row">
            <td>Group total</td>
            <td>{allocations.parent_amount != null ? formatMoney(allocations.parent_amount, currency) : '—'}</td>
            <td>{formatMoney(allocations.consumed_total, currency)}</td>
            <td>{pct(allocations.consumed_total, allocations.parent_amount)}</td>
            <td>{allocations.parent_amount != null ? formatMoney(allocations.parent_amount - allocations.consumed_total, currency) : '—'}</td>
            <td /><td /><td />
          </tr>
        </tbody>
      </table>
      <SeriesChart label="Signed against consumed, by affiliate" currency={currency} height={280}
                   categories={[...rows.map((row) => row.name), 'Unallocated (own)']}
                   series={[
                     { name: 'Signed MACC', data: [...rows.map((row) => row.commitment?.amount ?? null), allocations.unallocated], color: 'other' },
                     { name: 'Consumed', data: [...rows.map((row) => row.burn?.consumed ?? row.consumed_against_parent), allocations.own.consumed], color: 1 },
                   ]} />
      <p className="text-muted azure-cost-note">
        Every affiliate dollar counts against its own MACC and the group's. Consumption here is since each MACC's own
        start; the group total counts from the group's start.
      </p>
    </details>
  );
}

function GroupBanner({ analysis }: { analysis: Analysis }) {
  const parent = analysis.group.parent;
  if (!parent) return null;
  return (
    <p className="azure-cost-group-banner">
      An affiliate of <strong>{parent.name}</strong>
      {parent.amount != null ? <> — its MACC is carved out of the group's {formatMoney(parent.amount, parent.currency)}</> : null}.
    </p>
  );
}

function Card({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={`card azure-cost-card${wide ? ' azure-cost-wide' : ''}`}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function OverviewTab({ analysis }: { analysis: Analysis }) {
  const drill = useDrillOpener();
  // Jan..Dec against a year: the bar clicked is that month of that year.
  const pickMonthOfYear = drill ? (name: string, year: string) => {
    const index = MONTH_NAMES.indexOf(name);
    if (index >= 0 && /^\d{4}$/.test(year)) drill('month', `${year}-${String(index + 1).padStart(2, '0')}`);
  } : undefined;
  const board = analysis.dashboard;
  const currency = analysis.currency;
  const closed = board.monthly.filter((row) => !row.partial);
  const lines = [...new Set(board.mix.flatMap((row) => Object.keys(row.lines)))]
    .sort((a, b) => (a === 'Azure (other)' ? 1 : b === 'Azure (other)' ? -1 : a.localeCompare(b)));
  const comparison = board.this_vs_last_year;

  return (
    <>
      <GroupBanner analysis={analysis} />
      <Kpis analysis={analysis} />
      <CommitmentCard analysis={analysis} />
      <AllocationsCard analysis={analysis} />
      <Card title="Monthly consumption" wide>
        <TrendChart months={analysis.months} forecast={analysis.forecast.months} currency={currency} onPick={drill ? (month) => drill('month', month) : undefined} />
      </Card>
      <Card title="What it was spent on, by month" wide>
        <SeriesChart label="Plan-line mix by month" currency={currency} height={320} categoryLabel={(m) => formatMonth(m, true)} onPick={drill ? (month) => drill('month', month) : undefined}
                     categories={board.mix.map((row) => row.month)}
                     series={lines.map((line, index) => ({ name: line, stack: 'mix', data: board.mix.map((row) => row.lines[line] ?? 0),
                       color: line === 'Azure (other)' ? 'other' as const : index }))} />
      </Card>
      <SolutionPlaysCard analysis={analysis} />
      <div className="azure-cost-columns">
        <Card title="By year">
          <SeriesChart label="Consumption by year" currency={currency} categories={board.by_year.map((row) => String(row.year))}
                       series={[{ name: 'Total', data: board.by_year.map((row) => row.total) }]} />
        </Card>
        <Card title={`Year to date, same months${board.kpis.ytd_through ? ` (to ${formatMonth(board.kpis.ytd_through)})` : ''}`}>
          <SeriesChart label="Year to date by year" currency={currency} categories={board.ytd_by_year.map((row) => String(row.year))}
                       series={[{ name: 'YTD', data: board.ytd_by_year.map((row) => row.total), color: 1 }]} />
        </Card>
        <Card title="Month over month %">
          <SeriesChart label="Month over month change" currency={currency} percent categoryLabel={(m) => formatMonth(m, true)} onPick={drill ? (month) => drill('month', month) : undefined}
                       categories={closed.map((row) => row.month)} series={[{ name: 'MoM', data: closed.map((row) => row.mom_pct ?? null) }]} />
        </Card>
        <Card title="Year over year %">
          <SeriesChart label="Year over year change" currency={currency} percent categoryLabel={(m) => formatMonth(m, true)} onPick={drill ? (month) => drill('month', month) : undefined}
                       categories={closed.map((row) => row.month)}
                       series={[{ name: 'YoY', data: closed.map((row) => row.yoy_pct ?? null), color: 1 }]} />
        </Card>
        <Card title={`${comparison.last_year} against ${comparison.this_year}, by month`}>
          <SeriesChart label="This year against last year" currency={currency} categories={MONTH_NAMES} onPick={pickMonthOfYear}
                       series={[{ name: String(comparison.last_year), data: comparison.last, color: 'other' },
                         { name: String(comparison.this_year), data: comparison.this, color: 0 }]} />
        </Card>
        <Card title={`MoM growth %, ${comparison.last_year} against ${comparison.this_year}`}>
          <SeriesChart label="Month over month growth by year" currency={currency} percent categories={MONTH_NAMES} onPick={pickMonthOfYear}
                       series={[{ name: String(comparison.last_year), data: comparison.last_mom, color: 'other' },
                         { name: String(comparison.this_year), data: comparison.this_mom, color: 0 }]} />
        </Card>
      </div>
      {board.accounts.length > 1 ? (
        <Card title="By enrollment, by quarter" wide>
          <SeriesChart label="Quarterly consumption by enrollment" currency={currency}
                       categories={board.quarterly.map((row) => row.quarter)}
                       series={board.accounts.map((account) => ({ name: account, data: board.quarterly.map((row) => row.by_account[account] ?? 0) }))} />
        </Card>
      ) : null}
      {board.credit_details.length ? (
        <Card title="Credits applied" wide>
          <table className="azure-cost-table">
            <thead><tr><th>Month</th><th>Credit</th><th>Value</th></tr></thead>
            <tbody>
              {board.credit_details.map((row) => (
                <tr key={`${row.month}-${row.name}`}><td>{formatMonth(row.month)}</td><td>{row.name}</td>
                  <td>{formatMoney(row.value, currency)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      ) : null}
    </>
  );
}
