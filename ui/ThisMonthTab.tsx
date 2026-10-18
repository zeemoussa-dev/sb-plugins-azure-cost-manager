import { useCallback, useEffect, useRef, useState } from 'react';
import { SeriesChart } from './charts';
import {
  createOpportunity, fetchSyncStatus, fetchThisMonth, refreshThisMonth,
  type MonthRow, type ThisMonth, type View,
} from './client';
import { errorText, formatMoney, formatMonth } from './format';

const POLL_MS = 4000;

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

function Table({ rows, currency, caption }: { rows: MonthRow[]; currency: string | null; caption: string }) {
  if (!rows.length) return null;
  return (
    <table className="azure-cost-table">
      <thead><tr><th>{caption}</th><th>This month</th><th>Last month, same days</th><th>Change</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <td>{row.name}{row.new ? <span className="azure-cost-anomaly new"> new</span> : null}</td>
            <td>{formatMoney(row.this_month, currency)}</td>
            <td>{formatMoney(row.last_month_same_days, currency)}</td>
            <td>{row.change >= 0 ? '+' : ''}{formatMoney(row.change, currency)}
              {row.change_pct != null ? <span className="text-muted"> ({row.change_pct >= 0 ? '+' : ''}{row.change_pct}%)</span> : null}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** This month so far: is the customer on last month's pace, and what is new in
 *  the tenant -- early enough to open an opportunity. Refreshed only on demand. */
export function ThisMonthTab({ customerId, view }: { customerId: string; view: View }) {
  const [found, setFound] = useState<ThisMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
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
        setRefreshing(status.errors.length ? `Done, with ${status.errors.length} error(s): ${status.errors[0].message}` : null);
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
  const dims = found.dimensions!;
  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">
          {found.through ? `Data to ${found.through} (Azure lags a day or two)` : 'No day of this month billed yet'}
          {' · fetched '}{new Date(found.fetched_at!).toLocaleString()}
        </span>
        {refreshButton}
      </div>
      {refreshing ? <p className="text-muted azure-cost-note">{refreshing}</p> : null}

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
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">New workloads</span>
          <strong>{found.new_workloads?.length ?? 0}</strong>
          <span className="azure-cost-kpi-detail">services, subscriptions or resource groups</span></div>
      </div>

      <section className="card azure-cost-card">
        <h3>Day by day, this month against last</h3>
        <SeriesChart label="This month against last" currency={currency} height={280}
                     categories={daily.map((day) => String(day.day))}
                     series={[{ name: 'This month', kind: 'line', data: daily.map((day) => day.this_month_to_date), color: 0 },
                       { name: 'Last month', kind: 'line', dashed: true, data: daily.map((day) => day.last_month_to_date), color: 'other' }]} />
        <p className="text-muted azure-cost-note">Month to date, accumulated day by day.</p>
      </section>

      <section className="card azure-cost-card">
        <h3>New this month — possible opportunities</h3>
        <p className="text-muted azure-cost-note">
          Billed this month and not at all last month (nor, for a service or subscription, in the three months before).
          Every new workload is listed; a new resource group usually names a new project.
        </p>
        {found.new_workloads?.length ? (
          <table className="azure-cost-table">
            <thead><tr><th>Kind</th><th>Name</th><th>This month so far</th>{view === 'account' ? <th /> : null}</tr></thead>
            <tbody>
              {found.new_workloads.map((workload) => (
                <tr key={`${workload.kind}|${workload.name}`}>
                  <td>{workload.kind_label}</td>
                  <td>{workload.name}</td>
                  <td>{formatMoney(workload.this_month, currency)}</td>
                  {view === 'account' ? <td><NewWorkload found={found} kind={workload.kind_label} name={workload.name} cost={workload.this_month} /></td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-muted">Nothing new this month so far.</p>}
      </section>

      {(['service', 'subscription', 'resource_group'] as const).map((key) => (
        dims[key].movers.length ? (
          <section key={key} className="card azure-cost-card">
            <h3>Growing fastest — {dims[key].label.toLowerCase()}s</h3>
            <Table rows={dims[key].movers} currency={currency} caption={dims[key].label} />
          </section>
        ) : null
      ))}
    </>
  );
}
