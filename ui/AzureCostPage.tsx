import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import {
  BurnDownChart, Change, CommitmentGauge, RankedBars, StackedMonthsChart, TrendChart,
} from './charts';
import {
  fetchAnalysis, fetchConsumption, fetchSignIn, fetchTracked, refreshAccount,
  type Analysis, type ConsumptionRow, type SignInState, type TrackedAccount,
} from './client';
import { agreementLabel, errorText, formatMoney, formatMonth } from './format';

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
  const runRate = analysis.commitment?.run_rate
    ?? (() => {
      const closed = analysis.months.filter((month) => !month.partial).slice(-3);
      return closed.length ? closed.reduce((sum, month) => sum + month.actual, 0) / closed.length : null;
    })();
  return (
    <div className="azure-cost-kpis">
      <Kpi label={`Last month (${formatMonth(analysis.last_closed_month)})`}
           value={lastClosed ? formatMoney(lastClosed.actual, currency) : '—'}
           detail={lastClosed ? <Change pct={lastClosed.mom_pct} /> : null} />
      <Kpi label="This month so far" value={current ? formatMoney(current.actual, currency) : '—'} />
      <Kpi label="Run rate (3 closed months)" value={runRate != null ? formatMoney(runRate, currency) : '—'} />
      <Kpi label={`${analysis.forecast.year} forecast`}
           value={analysis.forecast.year_end_total != null ? formatMoney(analysis.forecast.year_end_total, currency) : '—'}
           detail={analysis.forecast.source ? `by ${analysis.forecast.source === 'azure' ? 'Azure' : 'run rate'}` : null} />
      {analysis.commitment ? (
        <Kpi label={analysis.commitment.kind === 'macc' ? 'MACC remaining' : 'Prepayment remaining'}
             value={formatMoney(analysis.commitment.remaining, analysis.commitment.currency)}
             detail={`${analysis.commitment.consumed_pct ?? '—'}% consumed`} />
      ) : null}
    </div>
  );
}

function CommitmentCard({ analysis }: { analysis: Analysis }) {
  const commitment = analysis.commitment;
  if (!commitment) {
    return (
      <section className="card azure-cost-card">
        <h3>Commitment</h3>
        <p className="text-muted">
          {analysis.errors.commitment ?? 'No commitment found on this agreement (no MACC lots or Azure Prepayment balance).'}
        </p>
      </section>
    );
  }
  const currency = commitment.currency;
  return (
    <section className="card azure-cost-card">
      <h3>{commitment.kind === 'macc' ? 'MACC burn-down' : 'Azure Prepayment balance'}</h3>
      <CommitmentGauge commitment={commitment} />
      <dl className="azure-cost-facts">
        <dt>Commitment</dt><dd>{formatMoney(commitment.original, currency)}</dd>
        <dt>Consumed</dt><dd>{formatMoney(commitment.consumed, currency)} ({commitment.consumed_pct ?? '—'}%)</dd>
        <dt>Remaining</dt><dd>{formatMoney(commitment.remaining, currency)}</dd>
        {commitment.end ? <><dt>Term</dt><dd>{commitment.start ?? '?'} → {commitment.end}</dd></> : null}
        <dt>Runs out</dt><dd>{commitment.projected_exhaustion ? formatMonth(commitment.projected_exhaustion) : '—'}</dd>
        {commitment.projected_shortfall ? (
          <><dt>Projected shortfall</dt><dd className="azure-cost-warning">{formatMoney(commitment.projected_shortfall, currency)}</dd></>
        ) : null}
      </dl>
      {commitment.verdict ? <p className="azure-cost-verdict">{commitment.verdict}</p> : null}
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

function AccountView({ account }: { account: TrackedAccount }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mix, setMix] = useState<ConsumptionRow[]>([]);
  const [mixBy, setMixBy] = useState<'service' | 'subscription'>('service');
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setRefreshing(true);
    setError(null);
    refreshAccount(account.name).then((result) => {
      setAnalysis(result);
      setRefreshing(false);
    }, (failure) => {
      setError(errorText(failure));
      setRefreshing(false);
    });
  }, [account.name]);

  // StrictMode runs effects twice; two refreshes would spend two throttled
  // Cost Management queries on the same months.
  const autoRefreshed = useRef(false);

  useEffect(() => {
    fetchAnalysis(account.name).then((result) => {
      setAnalysis(result);
      // Stale on open: the current month moves daily, so an old cache is refreshed
      // as the page opens rather than waiting for the button.
      if (result.stale && !autoRefreshed.current) {
        autoRefreshed.current = true;
        refresh();
      }
    }, (failure) => setError(errorText(failure)));
  }, [account.name, refresh]);

  const fetchedAt = analysis?.fetched_at;
  useEffect(() => {
    if (!fetchedAt) return;
    fetchConsumption(account.name, mixBy).then((result) => setMix(result.rows), () => setMix([]));
  }, [account.name, mixBy, fetchedAt]);

  const hasData = analysis && analysis.months.length > 0;

  return (
    <div className="azure-cost-account">
      <div className="azure-cost-toolbar">
        <span className="badge">{agreementLabel(account.agreement_type)}</span>
        <span className="text-muted">
          {analysis?.fetched_at ? `Refreshed ${new Date(analysis.fetched_at).toLocaleString()}` : 'Not refreshed yet'}
        </span>
        <button type="button" className="btn" onClick={refresh} disabled={refreshing}>
          {refreshing ? 'Refreshing from Azure…' : 'Refresh'}
        </button>
      </div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {analysis?.errors.forecast ? (
        <p className="text-muted azure-cost-note">Azure forecast unavailable, projecting from the run rate: {analysis.errors.forecast}</p>
      ) : null}
      {!hasData ? (
        !error && !refreshing ? <p className="empty-state">No consumption cached for this account yet.</p> : null
      ) : (
        <>
          <Kpis analysis={analysis} />
          <section className="card azure-cost-card">
            <h3>Monthly spend</h3>
            <TrendChart months={analysis.months} forecast={analysis.forecast.months} currency={analysis.currency} />
          </section>
          <section className="card azure-cost-card">
            <div className="azure-cost-card-head">
              <h3>Spend mix by month</h3>
              <div className="azure-cost-segmented">
                {(['service', 'subscription'] as const).map((group) => (
                  <button key={group} type="button" className={group === mixBy ? 'active' : undefined}
                          onClick={() => setMixBy(group)}>
                    {group === 'service' ? 'Services' : 'Subscriptions'}
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
          <CommitmentCard analysis={analysis} />
        </>
      )}
    </div>
  );
}

export function AzureCostPage() {
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [accounts, setAccounts] = useState<TrackedAccount[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSignIn().then(setSignIn, (failure) => setError(errorText(failure)));
    fetchTracked().then((tracked) => {
      setAccounts(tracked);
      setSelected((current) => current ?? tracked[0]?.name ?? null);
    }, (failure) => setError(errorText(failure)));
  }, []);

  const account = accounts?.find((candidate) => candidate.name === selected) ?? null;

  return (
    <div className="page azure-cost-page">
      <header className="azure-cost-header">
        <h1>Azure Cost</h1>
        {accounts && accounts.length > 0 ? (
          <select value={selected ?? ''} onChange={(event) => setSelected(event.target.value)}
                  aria-label="Billing account">
            {accounts.map((candidate) => (
              <option key={candidate.name} value={candidate.name}>
                {candidate.display_name} ({agreementLabel(candidate.agreement_type)})
              </option>
            ))}
          </select>
        ) : null}
        <Link to={SETTINGS} className="azure-cost-settings-link">Choose accounts</Link>
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {accounts && accounts.length === 0 ? (
        <p className="empty-state">
          No billing accounts tracked yet. <Link to={SETTINGS}>Choose the customers' billing accounts</Link> to follow.
        </p>
      ) : null}
      {account ? <AccountView key={account.name} account={account} /> : null}
    </div>
  );
}
