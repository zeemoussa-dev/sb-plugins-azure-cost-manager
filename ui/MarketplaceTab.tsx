import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart, type Series } from './charts';
import { fetchCustomerMarketplace, setMaccEligible, type MarketplaceReport, type MarketplaceSolution } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

export const PERIODS = ['12m', 'ytd', 'start'] as const;
export type Period = typeof PERIODS[number];
export const PERIOD_LABELS: Record<Period, string> = { '12m': 'Last 12 months', ytd: 'This year', start: 'From the start' };

export function periodRange(period: Period): { first?: string; last?: string } {
  const now = new Date();
  if (period === 'ytd') return { first: `${now.getFullYear()}-01` };
  // Everything synced; the report names the first month it actually has.
  if (period === 'start') return { first: 'start' };
  return {};
}

/** "Jan 2024 – Oct 2026", and say so when it runs from the first month on record. */
export function periodText(period: { first: string | null; last: string | null; from_start?: boolean }): string {
  if (!period.first || !period.last) return 'no Marketplace data synced';
  return `${period.from_start ? 'from ' : ''}${formatMonth(period.first)} – ${formatMonth(period.last)}`;
}

export function PeriodPicker({ period, onChange }: { period: Period; onChange: (period: Period) => void }) {
  return (
    <div className="azure-cost-segmented">
      {PERIODS.map((value) => (
        <button key={value} type="button" className={value === period ? 'active' : undefined} onClick={() => onChange(value)}>
          {PERIOD_LABELS[value]}
        </button>
      ))}
    </div>
  );
}

/** The switch that says whether an offer counts toward MACCs -- one setting for
 *  every customer, since Azure does not say. */
export function MaccSwitch({ publisher, offer, eligible, onChanged }: {
  publisher: string; offer: string; eligible: boolean; onChanged: () => void;
}) {
  const [saving, setSaving] = useState(false);
  return (
    <label className="azure-cost-check" title="Applies to this offer for every customer">
      <input type="checkbox" checked={eligible} disabled={saving}
             onChange={(event) => {
               setSaving(true);
               setMaccEligible(publisher, offer, event.target.checked).then(() => { setSaving(false); onChanged(); },
                 () => setSaving(false));
             }} />
      {eligible ? 'counts' : 'excluded'}
    </label>
  );
}

function SolutionsTable({ solutions, currency, onChanged, adopted }: {
  solutions: MarketplaceSolution[]; currency: string | null; onChanged: () => void; adopted?: boolean;
}) {
  return (
    <table className="azure-cost-table">
      <thead>
        <tr><th>Publisher</th><th>Solution</th><th>Plan</th><th>Kind</th>
          {adopted ? <th>First seen</th> : <><th>Total</th><th>Last month</th></>}
          <th>Subscriptions</th>{adopted ? null : <th>Toward MACC</th>}</tr>
      </thead>
      <tbody>
        {solutions.map((solution) => {
          const monthsSeen = Object.keys(solution.by_month).sort();
          const lastMonth = monthsSeen[monthsSeen.length - 1];
          return (
            <tr key={`${solution.publisher}|${solution.offer}|${solution.plan}`}>
              <td>{solution.publisher}</td>
              <td>{solution.offer}</td>
              <td className="text-muted">{solution.plan || '—'}</td>
              <td>{solution.kind}</td>
              {adopted ? <td>{formatMonth(solution.first_month)}</td> : (
                <>
                  <td>{formatMoney(solution.total, currency)}</td>
                  <td>{lastMonth ? `${formatMoney(solution.by_month[lastMonth], currency)} (${formatMonth(lastMonth, true)})` : '—'}</td>
                </>
              )}
              <td title={solution.subscriptions.join('\n')}>{solution.subscriptions.length}</td>
              {adopted ? null : (
                <td><MaccSwitch publisher={solution.publisher} offer={solution.offer} eligible={solution.macc_eligible}
                                onChanged={onChanged} /></td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const SHOWN_PUBLISHERS = 6;

function publisherSeries(report: MarketplaceReport, publishers: string[]): Series[] {
  const shown = publishers.slice(0, SHOWN_PUBLISHERS);
  const series: Series[] = shown.map((publisher, index) => ({
    name: publisher, stack: 'mp', color: index, data: report.monthly.map((row) => row.by_publisher[publisher] ?? 0),
  }));
  if (publishers.length > SHOWN_PUBLISHERS) {
    series.push({ name: 'Other publishers', stack: 'mp', color: 'other',
      data: report.monthly.map((row) => Object.entries(row.by_publisher)
        .filter(([name]) => !shown.includes(name)).reduce((sum, [, cost]) => sum + cost, 0)) });
  }
  return series;
}

export function MarketplaceTab({ customerId, currency, syncedVersion }: {
  customerId: string; currency: string | null; syncedVersion: number;
}) {
  const [period, setPeriod] = useUrlState<Period>('marketplace-period', '12m', { valid: PERIODS });
  const [report, setReport] = useState<MarketplaceReport | null>(null);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => setReloads((count) => count + 1), []);

  useEffect(() => {
    const { first, last } = periodRange(period);
    fetchCustomerMarketplace(customerId, first, last).then((result) => { setReport(result); setError(null); },
      (failure) => setError(errorText(failure)));
  }, [customerId, period, syncedVersion, reloads]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!report) return <Loading />;

  const publishers = report.publishers.map((publisher) => publisher.publisher);
  return (
    <>
      <div className="azure-cost-toolbar">
        <PeriodPicker period={period} onChange={setPeriod} />
        <Link to="/azure-cost-manager/marketplace" className="azure-cost-settings-link">Marketplace across all customers</Link>
      </div>
      <div className="azure-cost-kpis">
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Marketplace</span>
          <strong>{formatMoney(report.total, currency)}</strong>
          <span className="azure-cost-kpi-detail">{periodText(report.period)}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Toward the MACC</span>
          <strong>{formatMoney(report.macc, currency)}</strong>
          {report.not_macc ? <span className="azure-cost-kpi-detail">{formatMoney(report.not_macc, currency)} excluded</span> : null}</div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Solutions billed</span>
          <strong>{report.solutions.length}</strong>
          <span className="azure-cost-kpi-detail">from {report.publishers.length} publisher{report.publishers.length === 1 ? '' : 's'}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Adopted, no charge</span>
          <strong>{report.adopted.length}</strong></div>
      </div>
      {report.reconciliation.length ? (
        <p className="azure-cost-warning azure-cost-note">
          Itemised charges differ from the invoiced Marketplace in {report.reconciliation.length} month(s); they settle on the
          next sync: {report.reconciliation.map((gap) => `${formatMonth(gap.month, true)} ${formatMoney(gap.itemised, currency)} vs ${formatMoney(gap.invoiced, currency)}`).join(' · ')}
        </p>
      ) : null}
      {report.monthly.length ? (
        <section className="card azure-cost-card">
          <h3>Marketplace by month, by publisher</h3>
          <SeriesChart label="Marketplace by month and publisher" currency={currency} height={300}
                       categories={report.monthly.map((row) => row.month)} categoryLabel={(m) => formatMonth(m, true)}
                       series={publisherSeries(report, publishers)} />
        </section>
      ) : null}
      <section className="card azure-cost-card">
        <h3>Partner solutions bought</h3>
        {report.solutions.length ? (
          <SolutionsTable solutions={report.solutions} currency={currency} onChanged={reload} />
        ) : <p className="text-muted">No Marketplace solution billed in this period.</p>}
        <p className="text-muted azure-cost-note">
          Every Marketplace dollar counts toward the MACC unless its offer is excluded here; an exclusion applies to every
          customer and to the MACC consumed.
        </p>
      </section>
      {report.adopted.length ? (
        <section className="card azure-cost-card">
          <h3>Adopted, no charge in the period</h3>
          <p className="text-muted azure-cost-note">Free plans, trials, and models billed on another line: deployed, not yet paying.</p>
          <SolutionsTable solutions={report.adopted} currency={currency} onChanged={reload} adopted />
        </section>
      ) : null}
    </>
  );
}
