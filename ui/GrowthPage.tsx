import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { fetchGrowth, type GrowthRow, reportExportPath } from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink } from './ReportsHome';

const FILTERS = { all: 'All', growing: 'Growing', declining: 'Declining', signals: 'Stopped or dropped' } as const;
type Filter = keyof typeof FILTERS;

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${value}%`;
}

function Movement({ value }: { value: number | null | undefined }) {
  const className = value == null ? undefined : value >= 20 ? 'azure-cost-good' : value <= -20 ? 'azure-cost-warning' : undefined;
  return <span className={className}>{percent(value)}</span>;
}

/** Who is growing and who is falling away, across every customer (operator,
 *  2026-10-21): the measured monthly total over three and twelve months, last
 *  month against a year before, and what stopped or started. */
export function GrowthPage() {
  const [rows, setRows] = useState<GrowthRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchGrowth().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  const shown = useMemo(() => (rows ?? []).filter((row) => row.last_month && (
    filter === 'all' || (filter === 'growing' && row.status === 'growing')
    || (filter === 'declining' && row.status === 'declining')
    || (filter === 'signals' && row.signals.some((signal) => signal.kind === 'stopped' || signal.kind === 'drop')))),
  [rows, filter]);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Growth and churn' }]} />
      <header className="azure-cost-header">
        <h1>Growth and churn</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('growth'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        Closed months only. A change of 20% either way over three months is a signal; a service that cost $1,000 a
        month or more and fell below a tenth of that has stopped. Groups include their affiliates.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <section className="card azure-cost-card">
          <div className="azure-cost-chips" role="group" aria-label="Show">
            {(Object.keys(FILTERS) as Filter[]).map((name) => (
              <button key={name} type="button" className={filter === name ? 'active' : undefined}
                      aria-pressed={filter === name} onClick={() => setFilter(name)}>{FILTERS[name]}</button>
            ))}
          </div>
          <table className="azure-cost-table">
            <thead>
              <tr><th>Customer</th><th>Last month</th><th>Monthly, last 3</th><th>3 months</th><th>12 months</th>
                <th>Year on year</th><th>Signals</th></tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <Fragment key={row.id}>
                  <tr className={row.parent ? 'azure-cost-affiliate' : undefined}>
                    <td>
                      <button type="button" className="btn azure-cost-link-button"
                              onClick={() => setOpen(open === row.id ? null : row.id)}
                              aria-expanded={open === row.id}>{open === row.id ? '▾' : '▸'}</button>{' '}
                      <Link to={reportLink('Overview', row.id)}>{row.name}</Link>
                      {row.affiliates ? <span className="text-muted"> + {row.affiliates}</span> : null}
                    </td>
                    <td>{formatMoney(row.last_total ?? 0, row.currency, true)}
                      <span className="text-muted"> {row.last_month ? formatMonth(row.last_month, true) : ''}</span></td>
                    <td>{formatMoney(row.recent_monthly ?? 0, row.currency, true)}</td>
                    <td><Movement value={row.change_3m_pct} /></td>
                    <td><Movement value={row.change_12m_pct} /></td>
                    <td><Movement value={row.yoy_pct} /></td>
                    <td>{row.signals.map((signal) => (
                      <span key={signal.kind} className={`azure-cost-anomaly ${signal.kind === 'growing' || signal.kind === 'new' ? 'new' : 'spike'}`}
                            title={signal.text}>{signal.kind === 'drop' ? 'sharp drop' : signal.kind}</span>
                    ))}</td>
                  </tr>
                  {open === row.id ? (
                    <tr>
                      <td colSpan={7}>
                        <div className="azure-cost-columns">
                          <div>
                            <h4>By solution play, last 3 months against the 3 before (monthly)</h4>
                            <table className="azure-cost-table">
                              <tbody>
                                {(row.by_play ?? []).map((play) => (
                                  <tr key={play.play}><td><DrillLink kind="play" name={play.play} customerId={row.id} /></td><td>{formatMoney(play.recent, row.currency, true)}</td>
                                    <td>{play.change >= 0 ? '+' : '−'}{formatMoney(Math.abs(play.change), row.currency, true)}</td>
                                    <td><Movement value={play.change_pct} /></td></tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          <div>
                            <h4>Stopped</h4>
                            {row.stopped?.length ? (
                              <ul>{row.stopped.map((item) => (
                                <li key={item.service}><DrillLink kind="service" name={item.service} customerId={row.id} />: {formatMoney(item.before, row.currency, true)} a month before,
                                  {' '}{formatMoney(item.last, row.currency, true)} last month</li>))}</ul>
                            ) : <p className="text-muted">Nothing stopped.</p>}
                            <h4>New</h4>
                            {row.started?.length ? (
                              <ul>{row.started.map((item) => (
                                <li key={item.service}><DrillLink kind="service" name={item.service} customerId={row.id} />: {formatMoney(item.last, row.currency, true)} last month</li>))}</ul>
                            ) : <p className="text-muted">Nothing new.</p>}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
