import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { fetchHygiene, type HygieneRow, reportExportPath } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink } from './ReportsHome';

const TAGS = ['Environment', 'Project', 'Owner'];

/** Each customer's subscription estate beside its tag coverage (operator,
 *  2026-10-21): what is new, what went dormant, how much is tiny, how
 *  concentrated -- and how much of the spend can be shown back by tag. */
export function HygienePage() {
  const [rows, setRows] = useState<HygieneRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchHygiene().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Cost', to: '/azure-cost-manager' }, { label: 'Subscription and tag hygiene' }]} />
      <header className="azure-cost-header">
        <h1>Subscription and tag hygiene</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('hygiene'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        The last closed month. New: $100 a month or more and not billed in the three months before. Dormant: $100 a month
        or more over those three months, now under a tenth of it. Tiny: under $50. Tag coverage is the share of the month's
        spend carrying the tag (Sync tags to fill it). Groups include their affiliates.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <section className="card azure-cost-card">
          <table className="azure-cost-table">
            <thead>
              <tr><th>Customer</th><th>Subscriptions</th><th>New</th><th>Dormant</th><th>Tiny</th>
                <th>Top one's share</th>{TAGS.map((tag) => <th key={tag}>{tag} tagged</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.id}>
                  <tr>
                    <td>
                      <button type="button" className="btn azure-cost-link-button" aria-expanded={open === row.id}
                              onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? '▾' : '▸'}</button>{' '}
                      <Link to={reportLink('Breakdown', row.id)}>{row.name}</Link>
                    </td>
                    <td>{row.subscriptions}<span className="text-muted"> ({row.subscriptions_12m} in 12 months)</span></td>
                    <td>{row.new_count || '—'}</td>
                    <td className={row.dormant_count ? 'azure-cost-warning' : undefined}>{row.dormant_count || '—'}</td>
                    <td>{row.tiny || '—'}</td>
                    <td>{row.top_share_pct != null ? `${row.top_share_pct}%` : '—'}</td>
                    {TAGS.map((tag) => (
                      <td key={tag}>{!row.tags_synced ? <span className="text-muted">not synced</span>
                        : row.tag_coverage[tag] != null ? `${row.tag_coverage[tag]}%` : '—'}</td>
                    ))}
                  </tr>
                  {open === row.id ? (
                    <tr><td colSpan={6 + TAGS.length}>
                      <div className="azure-cost-columns">
                        <div>
                          <h4>New in {formatMonth(row.last_month)}</h4>
                          {row.new.length ? <ul>{row.new.map((item) => (
                            <li key={item.subscription}>{item.subscription}: {formatMoney(item.last, 'USD', true)}</li>))}</ul>
                            : <p className="text-muted">None.</p>}
                        </div>
                        <div>
                          <h4>Went dormant</h4>
                          {row.dormant.length ? <ul>{row.dormant.map((item) => (
                            <li key={item.subscription}>{item.subscription}: {formatMoney(item.before, 'USD', true)} a month
                              before, {formatMoney(item.last, 'USD', true)} now</li>))}</ul>
                            : <p className="text-muted">None.</p>}
                        </div>
                      </div>
                    </td></tr>
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
