import { useCallback, useEffect, useRef, useState } from 'react';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import {
  createOpportunity, fetchSyncStatus, fetchThisMonth, refreshThisMonth,
  type MonthRow, type ThisMonth, type View,
} from './client';
import { DrillLink } from './Drill';
import type { DrillKind } from './client';
import { errorText, formatMoney, formatMonth } from './format';

const POLL_MS = 4000;
// Long lists -- one customer had 51 new resource groups -- show this many, then "Show all".
const SHOWN = 15;
const FILTERS = ['all', 'new', 'growing'] as const;
type Filter = typeof FILTERS[number];
const FILTER_LABELS: Record<Filter, string> = { all: 'All', new: 'New this month', growing: 'Growing' };

function NewWorkload({ found, kind, name, cost }: { found: ThisMonth; kind: string; name: string; cost: number }) {
  const [state, setState] = useState<'idle' | 'saving' | 'done'>('idle');
  const [error, setError] = useState<string | null>(null);
  const owner = found.customer.entity_customer;
  if (!owner) return <span className="text-muted" title="Link this customer to its note in Settings">—</span>;
  if (state === 'done') return <span className="text-muted">Opportunity created</span>;
  // No consumption plan: a finding is a lead, not a forecast.
  const title = `${name} – new ${kind.toLowerCase()} this month (${formatMoney(cost, found.currency, true)} so far)`;
  return (
    <>
      <button type="button" className="btn" disabled={state === 'saving'} onClick={() => {
        setState('saving');
        createOpportunity(found.customer.id, owner, title, { status: 'Open', stage: 'Identified' }, [])
          .then(() => setState('done'), (failure) => { setState('idle'); setError(errorText(failure)); });
      }}>{state === 'saving' ? 'Creating…' : 'Create opportunity'}</button>
      {error ? <div className="azure-cost-error">{error}</div> : null}
    </>
  );
}

/** A table that shows its first rows and offers the rest. */
function Rows({ rows, caption, found, view, drillKind }: {
  rows: MonthRow[]; caption: string; found: ThisMonth; view: View; drillKind?: DrillKind;
}) {
  const [all, setAll] = useState(false);
  const currency = found.currency;
  if (!rows.length) return <p className="text-muted">Nothing here this month so far.</p>;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <>
      <table className="azure-cost-table">
        <thead><tr><th>{caption}</th><th>This month</th><th>Last month, same days</th><th>Change</th>
          {view === 'account' ? <th /> : null}</tr></thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.name}>
              <td>{drillKind ? <DrillLink kind={drillKind} name={row.name} /> : row.name}
                {row.new ? <span className="azure-cost-anomaly new"> new</span> : null}</td>
              <td>{formatMoney(row.this_month, currency)}</td>
              <td>{formatMoney(row.last_month_same_days, currency)}</td>
              <td>{row.change >= 0 ? '+' : ''}{formatMoney(row.change, currency)}
                {row.change_pct != null ? <span className="text-muted"> ({row.change_pct >= 0 ? '+' : ''}{row.change_pct}%)</span> : null}</td>
              {view === 'account' ? (
                <td>{row.new ? <NewWorkload found={found} kind={caption} name={row.name} cost={row.this_month} /> : null}</td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > SHOWN ? (
        <button type="button" className="btn azure-cost-link-button" onClick={() => setAll(!all)}>
          {all ? `Show the first ${SHOWN}` : `Show all ${rows.length}`}
        </button>
      ) : null}
    </>
  );
}

/** This month so far: is the customer on last month's pace, and what is new in
 *  the tenant -- early enough to open an opportunity. Refreshed only on demand.
 *  One grouping at a time and folding sections, because a large tenant has
 *  hundreds of resource groups (operator, 2026-10-18). */
export function ThisMonthTab({ customerId, view }: { customerId: string; view: View }) {
  const [found, setFound] = useState<ThisMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [group, setGroup] = useUrlState<string>('group', 'service');
  const [filter, setFilter] = useUrlState<Filter>('changes', 'all', { valid: FILTERS });
  const poll = useRef<number | undefined>(undefined);

  const load = useCallback(() => {
    fetchThisMonth(customerId).then((result) => { setFound(result); setError(null); },
      (failure) => setError(errorText(failure)));
  }, [customerId]);

  useEffect(() => { load(); return () => window.clearTimeout(poll.current); }, [load]);

  function watch() {
    fetchSyncStatus().then((status) => {
      if (status.running && (status.scope ?? '').endsWith(':this-month')) {
        setRefreshing(`Fetching this month by day… ${status.accounts_done} of ${status.accounts_total} enrollments`);
        poll.current = window.setTimeout(watch, POLL_MS);
      } else {
        setRefreshing(status.errors.length ? `Done, with ${status.errors.length} problem(s): ${status.errors[0].message}` : null);
        load();
      }
    }, () => { poll.current = window.setTimeout(watch, POLL_MS); });
  }

  function refresh() {
    setRefreshing('Starting…');
    refreshThisMonth(customerId).then((status) => {
      if (!status.started) { setRefreshing('Another sync is running; try again when it finishes.'); return; }
      watch();
    }, (failure) => setRefreshing(errorText(failure)));
  }

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!found) return <p className="text-muted">Loading…</p>;

  const refreshButton = view === 'account' ? (
    <button type="button" className="btn" onClick={refresh} disabled={Boolean(refreshing && !refreshing.startsWith('Done'))}>
      Refresh this month
    </button>
  ) : null;

  if (!found.has_data) {
    return (
      <>
        <p className="empty-state">This month has not been fetched by day yet. It is fetched only when you ask.</p>
        <div className="azure-cost-toolbar">{refreshButton}</div>
        {refreshing ? <p className="text-muted azure-cost-note">{refreshing}</p> : null}
      </>
    );
  }

  const currency = found.currency;
  const daily = found.daily ?? [];
  const dims = found.dimensions ?? {};
  const keys = Object.keys(dims);
  const chosen = dims[group] ? group : keys[0];
  const dimension = dims[chosen];
  const rows = filter === 'new' ? dimension.new
    : filter === 'growing' ? dimension.rows.filter((row) => !row.new && row.change > 0).sort((a, b) => b.change - a.change)
      : dimension.rows;
  const newByKind = keys.map((key) => [key, dims[key]] as const).filter(([, item]) => item.new.length);

  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">
          {found.through ? `Data to ${found.through} (Azure lags a day or two)` : 'No day of this month billed yet'}
          {' · fetched '}{new Date(found.fetched_at!).toLocaleString()}
          {keys.some((key) => key.startsWith('tag:')) ? '' : ' · tags: sync tags first, then refresh, to group by Project, Owner or Environment'}
        </span>
        {refreshButton}
      </div>
      {refreshing ? <p className="text-muted azure-cost-note">{refreshing}</p> : null}
      {found.missing_enrollments?.length ? (
        <div className="azure-cost-error">
          Incomplete: {found.missing_enrollments.length} enrollment(s) not fetched by day yet
          ({found.missing_enrollments.join(', ')}), so their spend is missing from every figure below.
          Refresh this month to fetch them.
        </div>
      ) : null}

      <div className="azure-cost-kpis">
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">{formatMonth(found.month!)} to date</span>
          <strong>{formatMoney(found.month_to_date ?? 0, currency)}</strong>
          <span className="azure-cost-kpi-detail">{found.days_elapsed} of {found.days_in_month} days</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Against last month, same days</span>
          <strong>{found.pace_pct == null ? '—' : `${found.pace_pct >= 0 ? '+' : ''}${found.pace_pct}%`}</strong>
          <span className="azure-cost-kpi-detail">{formatMoney(found.last_month_same_days ?? 0, currency)} then</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Projected month end</span>
          <strong>{found.projected_month_end == null ? '—' : formatMoney(found.projected_month_end, currency)}</strong>
          <span className="azure-cost-kpi-detail">last month {formatMoney(found.last_month_total ?? 0, currency)}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">New this month</span>
          <strong>{found.new_workloads?.length ?? 0}</strong>
          <span className="azure-cost-kpi-detail">
            {newByKind.map(([, item]) => `${item.new.length} ${item.label.toLowerCase()}`).join(' · ') || 'nothing new'}
          </span></div>
      </div>

      <details className="card azure-cost-card azure-cost-fold" open>
        <summary><h3>Day by day, this month against last</h3></summary>
        <SeriesChart label="This month against last" currency={currency} height={260}
                     categories={daily.map((day) => String(day.day))}
                     series={[{ name: 'This month', kind: 'line', data: daily.map((day) => day.this_month_to_date), color: 0 },
                       { name: 'Last month', kind: 'line', dashed: true, data: daily.map((day) => day.last_month_to_date), color: 'other' }]} />
        <p className="text-muted azure-cost-note">Month to date, accumulated day by day.</p>
      </details>

      <details className="card azure-cost-card azure-cost-fold" open>
        <summary><h3>What is changing — by {dimension.label.toLowerCase()}</h3></summary>
        <div className="azure-cost-toolbar">
          <div className="azure-cost-segmented" role="tablist" aria-label="Group by">
            {keys.map((key) => (
              <button key={key} type="button" role="tab" aria-selected={key === chosen}
                      className={key === chosen ? 'active' : undefined} onClick={() => setGroup(key)}>
                {dims[key].label}{dims[key].new.length ? <span className="azure-cost-chip-count">{dims[key].new.length} new</span> : null}
              </button>
            ))}
          </div>
          <div className="azure-cost-chips" role="group" aria-label="Show">
            {FILTERS.map((name) => (
              <button key={name} type="button" className={filter === name ? 'active' : undefined}
                      aria-pressed={filter === name} onClick={() => setFilter(name)}>{FILTER_LABELS[name]}</button>
            ))}
          </div>
        </div>
        <p className="text-muted azure-cost-note">
          New: billed this month and not at all last month
          {chosen === 'service' || chosen === 'subscription' ? ' (nor in the three months before)' : ''}.
          {chosen.startsWith('tag:') ? ' Tag values are folded as in the Tags report; untagged spend is left out.' : ''}
          {' '}Every new {dimension.label.toLowerCase()} is listed; you decide which is an opportunity.
        </p>
        <Rows key={`${chosen}|${filter}`} rows={rows} caption={dimension.label} found={found} view={view}
              drillKind={chosen === 'service' || chosen === 'subscription' ? chosen : undefined} />
      </details>
    </>
  );
}
