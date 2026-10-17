import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiUrl } from '../../pluginHost/api';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useUrlFilters } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import { fetchMarketplaceAcross, marketplaceExportPath, type MarketplaceAcross } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { MaccSwitch, PERIODS, PeriodPicker, periodRange, periodText, type Period } from './MarketplaceTab';
import { SyncControl } from './SyncControl';

/** Every partner solution across every customer: who bought what, what it is
 *  worth, and how much of it burns the customers' MACCs. */
export function MarketplacePage() {
  const [filters, setFilter] = useUrlFilters({ period: '12m', publisher: '', search: '', counted: false });
  const period = (PERIODS as readonly string[]).includes(filters.period) ? filters.period as Period : '12m';
  const [report, setReport] = useState<MarketplaceAcross | null>(null);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => setReloads((count) => count + 1), []);
  const range = periodRange(period);

  useEffect(() => {
    fetchMarketplaceAcross(range.first, range.last).then((result) => { setReport(result); setError(null); },
      (failure) => setError(errorText(failure)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, reloads]);

  const solutions = useMemo(() => (report?.solutions ?? []).filter((solution) =>
    (!filters.publisher || solution.publisher === filters.publisher)
    && (!filters.counted || solution.macc_eligible)
    && (!filters.search || `${solution.publisher} ${solution.offer} ${solution.customers.map((c) => c.name).join(' ')}`
      .toLowerCase().includes(filters.search.toLowerCase()))), [report, filters]);

  const buyers = (report?.customers ?? []).filter((customer) => customer.total);
  const billed = solutions.filter((solution) => Math.round(solution.total * 100) !== 0);
  const adopted = solutions.filter((solution) => Math.round(solution.total * 100) === 0);
  const currency = 'USD';

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Cost', to: '/azure-cost-manager' }, { label: 'Marketplace, all customers' }]} />
      <header className="azure-cost-header">
        <h1>Azure Marketplace</h1>
      </header>
      <SyncControl profiles="only" label="Sync all billing profiles" onSynced={reload} />
      <p className="text-muted azure-cost-note">
        Customers are synced in full. To see every buyer — customer or not — sync all billing profiles: each one's
        invoice totals and Marketplace charges from its term start (a few hours the first time; afterwards only new months).
      </p>
      <div className="azure-cost-toolbar azure-cost-tabs-row">
        <PeriodPicker period={period} onChange={(value) => setFilter('period', value)} />
        <a className="btn" href={apiUrl(marketplaceExportPath(range.first, range.last))}>Export to Excel</a>
      </div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!report ? <p className="text-muted">Loading…</p> : (
        <>
          <div className="azure-cost-kpis">
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Marketplace, all customers</span>
              <strong>{formatMoney(report.total, currency)}</strong>
              <span className="azure-cost-kpi-detail">{periodText(report.period)}</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Toward customers' MACCs</span>
              <strong>{formatMoney(report.macc, currency)}</strong>
              {report.not_macc ? <span className="azure-cost-kpi-detail">{formatMoney(report.not_macc, currency)} excluded</span> : null}</div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Partner solutions</span>
              <strong>{report.solutions.length}</strong>
              <span className="azure-cost-kpi-detail">{report.publishers.length} publishers</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Buyers</span>
              <strong>{report.customers.filter((customer) => customer.total).length}</strong>
              <span className="azure-cost-kpi-detail">
                {report.customers.filter((c) => c.total && !c.profile).length} customers ·{' '}
                {report.customers.filter((c) => c.total && c.profile).length} billing profiles</span></div>
          </div>
          <div className="azure-cost-columns">
            <section className="card azure-cost-card">
              <h3>Revenue by publisher</h3>
              <SeriesChart label="Marketplace revenue by publisher" currency={currency} height={300}
                           categories={report.publishers.slice(0, 12).map((p) => p.publisher)}
                           series={[{ name: 'Toward MACCs', data: report.publishers.slice(0, 12).map((p) => p.macc), stack: 'p', color: 0 },
                             { name: 'Excluded', data: report.publishers.slice(0, 12).map((p) => p.total - p.macc), stack: 'p', color: 'other' }]} />
            </section>
            <section className="card azure-cost-card">
              <h3>Top buyers</h3>
              <SeriesChart label="Marketplace by buyer" currency={currency} height={300}
                           categories={buyers.slice(0, 12).map((c) => c.name)}
                           series={[{ name: 'Customers', data: buyers.slice(0, 12).map((c) => (c.profile ? null : c.total)), stack: 'b', color: 1 },
                             { name: 'Billing profiles (no customer yet)', data: buyers.slice(0, 12).map((c) => (c.profile ? c.total : null)), stack: 'b', color: 'other' }]} />
            </section>
          </div>
          <section className="card azure-cost-card">
            <h3>Buyers</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Customer / billing profile</th><th>Marketplace</th><th>Toward MACC</th><th>Solutions</th>
                <th>Top publisher</th><th>Consumption</th><th>Marketplace share</th></tr></thead>
              <tbody>
                {buyers.map((buyer) => (
                  <tr key={buyer.id}>
                    <td>{buyer.name}
                      {buyer.parent ? <span className="text-muted"> · affiliate</span> : null}
                      {buyer.profile ? <span className="azure-cost-anomaly new"> not a customer yet</span> : null}</td>
                    <td>{formatMoney(buyer.total, currency)}</td>
                    <td>{formatMoney(buyer.macc, currency)}</td>
                    <td>{buyer.solutions}</td>
                    <td>{buyer.top_publisher ?? '—'}</td>
                    <td>{buyer.consumption ? formatMoney(buyer.consumption, currency) : '—'}</td>
                    <td>{buyer.consumption ? `${Math.round((buyer.total / buyer.consumption) * 1000) / 10}%` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card azure-cost-card">
            <h3>By month</h3>
            <SeriesChart label="Marketplace by month" currency={currency} height={260}
                         categories={report.monthly.map((m) => m.month)} categoryLabel={(m) => formatMonth(m, true)}
                         series={[{ name: 'Toward MACCs', data: report.monthly.map((m) => m.macc), stack: 'm', color: 0 },
                           { name: 'Excluded', data: report.monthly.map((m) => m.total - m.macc), stack: 'm', color: 'other' }]} />
          </section>
          <section className="card azure-cost-card">
            <div className="azure-cost-card-head">
              <h3>Partner solutions</h3>
              <div className="azure-cost-toolbar">
                <select value={filters.publisher} onChange={(event) => setFilter('publisher', event.target.value)}>
                  <option value="">All publishers</option>
                  {report.publishers.map((p) => <option key={p.publisher} value={p.publisher}>{p.publisher}</option>)}
                </select>
                <input type="search" placeholder="Search solution or customer" value={filters.search}
                       onChange={(event) => setFilter('search', event.target.value)} />
                <label className="azure-cost-check">
                  <input type="checkbox" checked={filters.counted} onChange={(event) => setFilter('counted', event.target.checked)} />
                  Toward MACC only
                </label>
              </div>
            </div>
            <table className="azure-cost-table">
              <thead><tr><th>Publisher</th><th>Solution</th><th>Kind</th><th>Revenue</th><th>Customers</th><th>Bought by</th><th>Toward MACC</th></tr></thead>
              <tbody>
                {billed.map((solution) => (
                  <tr key={`${solution.publisher}|${solution.offer}`}>
                    <td>{solution.publisher}</td>
                    <td title={solution.plans.join('\n')}>{solution.offer}</td>
                    <td>{solution.kind}</td>
                    <td>{formatMoney(solution.total, currency)}</td>
                    <td>{solution.adopted_by}</td>
                    <td className="text-muted">{solution.customers.map((c) => `${c.name} (${formatMoney(c.total, currency, true)})`).join(' · ')}</td>
                    <td><MaccSwitch publisher={solution.publisher} offer={solution.offer} eligible={solution.macc_eligible} onChanged={reload} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {adopted.length ? (
              <>
                <h4>Adopted, no charge in the period</h4>
                <p className="text-muted azure-cost-note">
                  {adopted.map((solution) => `${solution.publisher} — ${solution.offer} (${solution.customers.map((c) => c.name).join(', ')})`).join(' · ')}
                </p>
              </>
            ) : null}
          </section>
        </>
      )}
    </div>
  );
}
