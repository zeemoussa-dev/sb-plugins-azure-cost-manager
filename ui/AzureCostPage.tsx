import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import {
  BurnDownChart, Change, CommitmentGauge, RankedBars, StackedMonthsChart, TrendChart,
} from './charts';
import {
  fetchAnalysis, fetchConsumption, fetchCustomers, fetchSignIn,
  type Analysis, type ConsumptionRow, type Customer, type MixGroup, type SignInState,
} from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { SyncControl } from './SyncControl';

const SETTINGS = '/settings/plugins/azure-cost-manager';

function Kpi({ label, value, detail }: { label: string; value: string; detail?: ReactNode }) {
  return (
    <div className="azure-cost-kpi card">
      <span className="azure-cost-kpi-label">{label}</span>
      <strong>{value}</strong>
      {detail ? <span className="azure-cost-kpi-detail">{detail}</span> : null}
    </div>
  );
}

function Kpis({ analysis }: { analysis: Analysis }) {
  const currency = analysis.currency;
  const lastClosed = analysis.months.find((month) => month.month === analysis.last_closed_month);
  const current = analysis.months.find((month) => month.partial);
  const closed = analysis.months.filter((month) => !month.partial).slice(-3);
  const runRate = closed.length ? closed.reduce((sum, month) => sum + month.actual, 0) / closed.length : null;
  const commitment = analysis.commitment;
  return (
    <div className="azure-cost-kpis">
      {commitment ? (
        <Kpi label={`Signed (${commitment.type})`} value={formatMoney(commitment.amount, commitment.currency)}
             detail={`${commitment.start} → ${commitment.end}`} />
      ) : null}
      {commitment ? (
        <Kpi label="Consumed since term start" value={formatMoney(commitment.consumed, commitment.currency)}
             detail={`${commitment.consumed_pct}% consumed · ${commitment.elapsed_pct}% of term elapsed`} />
      ) : null}
      <Kpi label={`Last month (${formatMonth(analysis.last_closed_month)})`}
           value={lastClosed ? formatMoney(lastClosed.actual, currency) : '—'}
           detail={lastClosed && lastClosed.mom_pct != null ? <Change pct={lastClosed.mom_pct} /> : null} />
      <Kpi label="This month so far" value={current ? formatMoney(current.actual, currency) : '—'} />
      <Kpi label="Run rate (3 closed months)" value={runRate != null ? formatMoney(runRate, currency) : '—'} />
      <Kpi label={`${analysis.forecast.year} forecast`}
           value={analysis.forecast.year_end_total != null ? formatMoney(analysis.forecast.year_end_total, currency) : '—'}
           detail={analysis.forecast.source ? `by ${analysis.forecast.source === 'azure' ? 'Azure' : 'run rate'}` : null} />
    </div>
  );
}

function CommitmentCard({ analysis, customerId }: { analysis: Analysis; customerId: string }) {
  const commitment = analysis.commitment;
  if (!commitment) {
    return (
      <section className="card azure-cost-card">
        <h3>Signed value</h3>
        <p className="text-muted">
          No signed value entered for this customer. Azure does not report it for indirect agreements —{' '}
          <Link to={`${SETTINGS}?customer=${encodeURIComponent(customerId)}`}>enter it in Settings</Link>.
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
        <dt>Term</dt><dd>{commitment.start} → {commitment.end} ({commitment.elapsed_pct}% elapsed)</dd>
        <dt>Consumed</dt><dd>{formatMoney(commitment.consumed, currency)} ({commitment.consumed_pct}%)</dd>
        <dt>Remaining</dt><dd>{formatMoney(commitment.remaining, currency)}</dd>
        <dt>Against an even pace</dt>
        <dd className={commitment.pace_gap < 0 ? 'azure-cost-warning' : undefined}>
          {commitment.pace_gap >= 0 ? 'ahead by ' : 'behind by '}{formatMoney(Math.abs(commitment.pace_gap), currency)}
        </dd>
        <dt>At term end, at run rate</dt><dd>{formatMoney(commitment.projected_at_end, currency)}</dd>
        {commitment.projected_exhaustion ? (
          <><dt>Fully consumed by</dt><dd>{formatMonth(commitment.projected_exhaustion)}</dd></>
        ) : null}
        {commitment.projected_shortfall ? (
          <><dt>Projected shortfall</dt><dd className="azure-cost-warning">{formatMoney(commitment.projected_shortfall, currency)}</dd></>
        ) : null}
      </dl>
      <p className="azure-cost-verdict">{commitment.verdict}</p>
      <BurnDownChart commitment={commitment} today={new Date()} />
    </section>
  );
}

function AnomalyList({ analysis }: { analysis: Analysis }) {
  const label = { spike: 'Spike', drop: 'Drop', new: 'New' } as const;
  return (
    <section className="card azure-cost-card">
      <h3>Anomalies in {formatMonth(analysis.last_closed_month)}</h3>
      {analysis.anomalies.length === 0 ? (
        <p className="text-muted">Nothing moved sharply against its last three months.</p>
      ) : (
        <table className="azure-cost-table">
          <thead><tr><th>Service</th><th>Kind</th><th>Month</th><th>3-month baseline</th><th>Change</th></tr></thead>
          <tbody>
            {analysis.anomalies.map((anomaly) => (
              <tr key={anomaly.service}>
                <td>{anomaly.service}</td>
                <td><span className={`azure-cost-anomaly ${anomaly.kind}`}>{label[anomaly.kind]}</span></td>
                <td>{formatMoney(anomaly.cost, analysis.currency)}</td>
                <td>{formatMoney(anomaly.baseline, analysis.currency)}</td>
                <td>{anomaly.change > 0 ? '+' : ''}{formatMoney(anomaly.change, analysis.currency)}
                  {anomaly.change_pct != null ? ` (${anomaly.change_pct > 0 ? '+' : ''}${anomaly.change_pct}%)` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const MIX_LABELS: Record<MixGroup, string> = { service: 'Services', subscription: 'Subscriptions', account: 'Enrollments' };

function CustomerView({ customerId, syncedVersion }: { customerId: string; syncedVersion: number }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mix, setMix] = useState<ConsumptionRow[]>([]);
  const [mixBy, setMixBy] = useState<MixGroup>('service');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAnalysis(customerId).then(setAnalysis, (failure) => setError(errorText(failure)));
  }, [customerId, syncedVersion]);

  useEffect(() => {
    fetchConsumption(customerId, mixBy).then((result) => setMix(result.rows), () => setMix([]));
  }, [customerId, mixBy, syncedVersion]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!analysis) return <p className="text-muted">Loading…</p>;

  const accountErrors = Object.entries(analysis.errors);
  const nothingSynced = analysis.months.length === 0;
  const nothingBilled = !nothingSynced && analysis.months.every((month) => !month.actual && !month.amortized);

  return (
    <div className="azure-cost-account">
      <p className="text-muted azure-cost-note">
        {analysis.customer.accounts.length} enrollment{analysis.customer.accounts.length === 1 ? '' : 's'}:{' '}
        {analysis.customer.accounts.map((account) => `${account.display_name} (${account.name})`).join(' · ')}
        {analysis.stale && analysis.synced_at ? ' — data is over a week old' : ''}
      </p>
      {accountErrors.length ? (
        <p className="text-muted azure-cost-note">
          Some months could not be fetched and will be retried on the next sync:{' '}
          {accountErrors.map(([account, errors]) => `${account}: ${Object.keys(errors).join(', ')}`).join('; ')}
        </p>
      ) : null}
      {nothingSynced ? (
        <p className="empty-state">Nothing synced for this customer yet. Sync it to load its consumption.</p>
      ) : nothingBilled ? (
        <p className="empty-state">Nothing was billed on these enrollments in the synced period.</p>
      ) : (
        <>
          <Kpis analysis={analysis} />
          <CommitmentCard analysis={analysis} customerId={customerId} />
          <section className="card azure-cost-card">
            <h3>Monthly spend</h3>
            <TrendChart months={analysis.months} forecast={analysis.forecast.months} currency={analysis.currency} />
          </section>
          <section className="card azure-cost-card">
            <div className="azure-cost-card-head">
              <h3>Spend mix by month</h3>
              <div className="azure-cost-segmented">
                {(Object.keys(MIX_LABELS) as MixGroup[]).map((group) => (
                  <button key={group} type="button" className={group === mixBy ? 'active' : undefined}
                          onClick={() => setMixBy(group)}>
                    {MIX_LABELS[group]}
                  </button>
                ))}
              </div>
            </div>
            <StackedMonthsChart rows={mix} groupKey={mixBy} currency={analysis.currency} />
          </section>
          <div className="azure-cost-columns">
            <section className="card azure-cost-card">
              <h3>Top services, {formatMonth(analysis.top_services.month)}</h3>
              <RankedBars rows={analysis.top_services.rows} currency={analysis.currency} />
              {analysis.top_services.others ? (
                <p className="text-muted azure-cost-note">All other services: {formatMoney(analysis.top_services.others, analysis.currency)}</p>
              ) : null}
            </section>
            <section className="card azure-cost-card">
              <h3>Subscriptions, {formatMonth(analysis.subscriptions.month)}</h3>
              <RankedBars rows={analysis.subscriptions.rows.slice(0, 10)} currency={analysis.currency} />
            </section>
          </div>
          <AnomalyList analysis={analysis} />
        </>
      )}
    </div>
  );
}

export function AzureCostPage() {
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [syncedVersion, setSyncedVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const loadCustomers = useCallback(() => {
    fetchCustomers().then((listed) => {
      setCustomers(listed);
      setSelected((current) => current && listed.some((customer) => customer.id === current)
        ? current : listed[0]?.id ?? null);
    }, (failure) => setError(errorText(failure)));
  }, []);

  useEffect(() => {
    fetchSignIn().then(setSignIn, () => setSignIn(null));
    loadCustomers();
  }, [loadCustomers]);

  const onSynced = useCallback(() => {
    loadCustomers();
    setSyncedVersion((version) => version + 1);
  }, [loadCustomers]);

  const customer = customers?.find((candidate) => candidate.id === selected) ?? null;

  return (
    <div className="page azure-cost-page">
      <header className="azure-cost-header">
        <h1>Azure Cost</h1>
        {customers && customers.length > 0 ? (
          <select value={selected ?? ''} onChange={(event) => setSelected(event.target.value)}
                  aria-label="Customer" className="azure-cost-picker">
            {customers.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
            ))}
          </select>
        ) : null}
        <Link to={SETTINGS} className="azure-cost-settings-link">Customers</Link>
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {customers && customers.length === 0 ? (
        <p className="empty-state">
          No customers yet. <Link to={SETTINGS}>Add a customer</Link> and pick its enrollments.
        </p>
      ) : null}
      {customer ? (
        <>
          <SyncControl customerId={customer.id} syncedAt={customer.synced_at} onSynced={onSynced} />
          <CustomerView key={customer.id} customerId={customer.id} syncedVersion={syncedVersion} />
        </>
      ) : null}
    </div>
  );
}
