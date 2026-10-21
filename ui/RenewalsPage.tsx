import { useEffect, useMemo, useState } from 'react';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { fetchRenewals, type RenewalRow, reportExportPath } from './client';
import { errorText, formatMoney, formatMonth } from './format';

const WINDOWS = { 3: 'Next 3 months', 12: 'Next 12 months', overdue: 'Overdue' } as const;
type Window = keyof typeof WINDOWS;

function monthsAhead(month: string, today: Date): number {
  return (Number(month.slice(0, 4)) - today.getFullYear()) * 12 + Number(month.slice(5, 7)) - (today.getMonth() + 1);
}

/** When each recurring Marketplace purchase next charges, and for how much
 *  (operator, 2026-10-21) -- read from the charges, as Azure gives no renewal date. */
export function RenewalsPage() {
  const [rows, setRows] = useState<RenewalRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [window, setWindow] = useState<Window>(3);
  const [monthly, setMonthly] = useState(false);

  useEffect(() => {
    fetchRenewals().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  const today = new Date();
  const shown = useMemo(() => (rows ?? []).filter((row) => (monthly || row.cadence_months !== 1) && (
    window === 'overdue' ? row.status === 'overdue'
      : row.status !== 'overdue' && monthsAhead(row.next_month, today) < Number(window))),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [rows, window, monthly]);
  const total = shown.reduce((sum, row) => sum + row.last_amount, 0);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Cost', to: '/azure-cost-manager' }, { label: 'Marketplace renewals' }]} />
      <header className="azure-cost-header">
        <h1>Marketplace renewals</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('renewals'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        Recurring Marketplace charges, per customer, offer, plan and subscription. The cadence is the usual gap between
        charges; one charged only once is taken as yearly. Overdue: the expected month passed with no charge — renewed
        another way, or cancelled.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <section className="card azure-cost-card">
          <div className="azure-cost-toolbar">
            <div className="azure-cost-chips" role="group" aria-label="When">
              {(Object.keys(WINDOWS) as Window[]).map((name) => (
                <button key={name} type="button" className={String(window) === String(name) ? 'active' : undefined}
                        onClick={() => setWindow(name)}>{WINDOWS[name]}</button>
              ))}
            </div>
            <label className="azure-cost-check">
              <input type="checkbox" checked={monthly} onChange={(event) => setMonthly(event.target.checked)} />
              Include monthly subscriptions
            </label>
            <span className="text-muted">{shown.length} renewals · {formatMoney(total, 'USD', true)} at their last charge</span>
          </div>
          <table className="azure-cost-table">
            <thead><tr><th>Expected</th><th>Customer</th><th>Publisher</th><th>Offer · plan</th><th>Cadence</th>
              <th>Last charge</th></tr></thead>
            <tbody>
              {shown.map((row) => (
                <tr key={`${row.customer}|${row.publisher}|${row.offer}|${row.plan}|${row.subscription}`}>
                  <td className={row.status === 'overdue' ? 'azure-cost-warning' : undefined}>
                    {formatMonth(row.next_month)}{row.status === 'overdue' ? ' (overdue)' : ''}</td>
                  <td>{row.customer}</td>
                  <td>{row.publisher}{row.core42 ? <span className="azure-cost-anomaly new"> Core42</span> : null}</td>
                  {/* Azure's offer name often ends with the plan already. */}
                  <td>{row.offer}{row.plan && !row.offer.includes(row.plan) ? <span className="text-muted"> · {row.plan}</span> : null}</td>
                  <td>{row.cadence}{row.cadence_assumed ? <span className="text-muted" title="Charged once so far"> (assumed)</span> : null}</td>
                  <td>{formatMoney(row.last_amount, 'USD', true)} <span className="text-muted">{formatMonth(row.last_month, true)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
