import { Fragment, useEffect, useState } from 'react';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { fetchMarketplaceWhitespace, type MarketplaceWhitespace, reportExportPath } from './client';
import { errorText, formatMoney, formatMonth } from './format';

/** What customers buy on the Marketplace from publishers other than Core42
 *  (operator, 2026-10-21): by category, with the leading offers, and by customer
 *  with how much of its Marketplace already goes to Core42. */
export function MarketplaceWhitespacePage() {
  const [report, setReport] = useState<MarketplaceWhitespace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchMarketplaceWhitespace().then(setReport, (failure) => setError(errorText(failure)));
  }, []);

  const period = report?.period;
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Marketplace whitespace' }]} />
      <header className="azure-cost-header">
        <h1>Marketplace whitespace</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('marketplace-whitespace'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        {period ? `${period.first ? formatMonth(period.first) : 'From the start'} to ${formatMonth(period.last)}. ` : ''}
        Marketplace charges from every customer and billing profile. A category is read from the publisher's and
        offer's names. Spend that counts toward a MACC is spend a Core42 offer could take instead.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!report ? <p className="text-muted">Loading…</p> : (
        <>
          <div className="azure-cost-kpis">
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Other publishers</span>
              <strong>{formatMoney(report.third_party, 'USD')}</strong></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Core42's offers</span>
              <strong>{formatMoney(report.core42, 'USD')}</strong>
              <span className="azure-cost-kpi-detail">{report.core42_share_pct != null ? `${report.core42_share_pct}% of all Marketplace` : ''}</span></div>
          </div>
          <section className="card azure-cost-card">
            <h3>By category</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Category</th><th>Spend</th><th>Toward MACCs</th><th>Customers</th><th>Leading offers</th></tr></thead>
              <tbody>
                {report.categories.map((category) => (
                  <Fragment key={category.category}>
                    <tr>
                      <td>
                        <button type="button" className="btn azure-cost-link-button" aria-expanded={open === category.category}
                                onClick={() => setOpen(open === category.category ? null : category.category)}>
                          {open === category.category ? '▾' : '▸'}</button>{' '}{category.category}
                      </td>
                      <td>{formatMoney(category.total, 'USD', true)}</td>
                      <td>{formatMoney(category.macc_eligible, 'USD', true)}</td>
                      <td>{category.customers}</td>
                      <td>{category.solutions.slice(0, 2).map((item) => item.publisher).join(' · ')}</td>
                    </tr>
                    {open === category.category ? (
                      <tr><td colSpan={5}>
                        <table className="azure-cost-table">
                          <thead><tr><th>Publisher</th><th>Offer</th><th>Kind</th><th>Spend</th><th>Customers</th></tr></thead>
                          <tbody>
                            {category.solutions.map((item) => (
                              <tr key={`${item.publisher}|${item.offer}`}>
                                <td>{item.publisher}</td><td>{item.offer}</td><td>{item.kind ?? ''}</td>
                                <td>{formatMoney(item.total, 'USD', true)}{item.macc_eligible ? '' : <span className="text-muted"> (not toward MACC)</span>}</td>
                                <td>{item.customers}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td></tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card azure-cost-card">
            <h3>By customer</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Customer or billing profile</th><th>Other publishers</th><th>Toward its MACC</th>
                <th>Core42's share</th><th>Categories</th></tr></thead>
              <tbody>
                {report.customers.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td>{formatMoney(row.third_party, 'USD', true)}</td>
                    <td>{formatMoney(row.macc_eligible, 'USD', true)}</td>
                    <td>{row.core42_share_pct != null ? `${row.core42_share_pct}%` : '—'}</td>
                    <td>{Object.entries(row.by_category).slice(0, 3)
                      .map(([name, cost]) => `${name} ${formatMoney(cost, 'USD', true)}`).join(' · ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
