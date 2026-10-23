import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { fetchFinOpsAcross, refreshPrices, type FinOpsAcrossRow } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink } from './ReportsHome';

const BUDGET_STATUS = { over: 'Over last month', 'forecast-over': 'Forecast over', within: 'Within' } as const;

/** Every customer ranked by steady on-demand spend: where the savings
 *  conversations are. The operator's view only -- it names every customer. */
export function FinOpsPage() {
  const [rows, setRows] = useState<FinOpsAcrossRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pricing, setPricing] = useState<string | null>(null);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    fetchFinOpsAcross().then(setRows, (failure) => setError(errorText(failure)));
  }, [reloads]);

  function priceNow() {
    setPricing('Pricing…');
    refreshPrices().then((result) => {
      setPricing(`Priced ${result.priced} meter${result.priced === 1 ? '' : 's'}${result.failed.length ? `, ${result.failed.length} failed` : ''}.`);
      setReloads((count) => count + 1);
    }, (failure) => setPricing(errorText(failure)));
  }

  const withMeters = (rows ?? []).filter((row) => row.has_meters);
  const steady = withMeters.reduce((sum, row) => sum + row.candidates_monthly, 0);
  const saving = withMeters.reduce((sum, row) => sum + (row.savings_monthly.ri_3y ?? 0), 0);
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Optimization opportunities' }]} />
      <header className="azure-cost-header">
        <h1>Optimization opportunities</h1>
        <button type="button" className="btn azure-cost-settings-link" onClick={priceNow}>Price candidates now</button>
      </header>
      {pricing ? <p className="text-muted azure-cost-note">{pricing}</p> : null}
      <p className="text-muted azure-cost-note">
        Each customer (a group with its affiliates) by the on-demand spend that ran steadily enough to commit to, and by
        how much of its reservable spend commitments already cover. Fully synced customers only: billing profiles synced
        lightly have no meter detail.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <>
          <div className="azure-cost-kpis">
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Steady on demand</span>
              <strong>{formatMoney(steady, 'USD')}</strong>
              <span className="azure-cost-kpi-detail">a month, across {withMeters.length} customers</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Estimated saving</span>
              <strong>{formatMoney(saving, 'USD')}</strong>
              <span className="azure-cost-kpi-detail">a month on 3-year reservations, priced meters only</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Customers with candidates</span>
              <strong>{withMeters.filter((row) => row.candidates).length}</strong></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Over budget</span>
              <strong>{rows.filter((row) => row.budget?.status === 'over').length}</strong>
              <span className="azure-cost-kpi-detail">last month</span></div>
          </div>
          <section className="card azure-cost-card">
            <table className="azure-cost-table">
              <thead><tr><th>Customer</th><th>Steady on demand / month</th><th>Save / month, 1-yr plan</th>
                <th>Save / month, 3-yr reservation</th><th>Candidates</th><th>Largest</th>
                <th>Coverage</th><th>On demand, reservable</th><th>Budget</th></tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td><Link to={reportLink('FinOps', row.id)}>{row.name}</Link>
                      {row.affiliates.length ? <span className="text-muted"> · group of {row.affiliates.length + 1}</span> : null}</td>
                    {row.has_meters ? (
                      <>
                        <td>{formatMoney(row.candidates_monthly, row.currency)}</td>
                        <td>{row.savings_monthly.sp_1y ? formatMoney(row.savings_monthly.sp_1y, row.currency) : '—'}</td>
                        <td>{row.savings_monthly.ri_3y ? formatMoney(row.savings_monthly.ri_3y, row.currency) : '—'}</td>
                        <td>{row.candidates}</td>
                        <td className="text-muted">{row.top_candidate ?? '—'}</td>
                        <td>{row.coverage_pct == null ? '—' : `${row.coverage_pct}%`}
                          {row.coverage_month ? <span className="text-muted"> · {formatMonth(row.coverage_month, true)}</span> : null}</td>
                        <td>{row.on_demand == null ? '—' : formatMoney(row.on_demand, row.currency)}</td>
                      </>
                    ) : <td colSpan={7} className="text-muted">No meter detail synced yet</td>}
                    <td>{row.budget ? `${formatMoney(row.budget.amount, row.currency, true)} · ${BUDGET_STATUS[row.budget.status]}` : '—'}</td>
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
