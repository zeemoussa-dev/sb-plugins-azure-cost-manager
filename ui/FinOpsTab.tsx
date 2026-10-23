import { useEffect, useState } from 'react';
import { SeriesChart } from './charts';
import {
  createOpportunity, fetchFinOps, OPTION_LABELS,
  type Budget, type FinOps, type Growth, type SteadyCandidate, type View,
} from './client';
import { DrillLink, useDrillOpener } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

/** The flexible option and the deepest one: what a conversation starts and ends with. */
const SHOWN_OPTIONS = ['sp_1y', 'ri_3y'] as const;

function bestOption(candidate: SteadyCandidate) {
  const savings = candidate.savings ?? {};
  return (Object.keys(savings) as (keyof typeof OPTION_LABELS)[])
    .sort((a, b) => (savings[b] ?? 0) - (savings[a] ?? 0))[0];
}

/** Files a finding as an Opportunity under the customer's note -- with no
 *  consumption plan, so a saving never inflates the pipeline forecast. */
function CreateOpportunity({ found, candidate }: { found: FinOps; candidate: SteadyCandidate }) {
  const [state, setState] = useState<'idle' | 'saving' | 'done'>('idle');
  const [error, setError] = useState<string | null>(null);
  const owner = found.customer.entity_customer;
  if (!owner) return <span className="text-muted" title="Link this customer to its Customer note in Settings">—</span>;
  if (state === 'done') return <span className="text-muted">Opportunity created</span>;
  const option = bestOption(candidate);
  const saving = option ? candidate.savings?.[option] : null;
  const title = option && saving
    ? `${candidate.meter} – ${OPTION_LABELS[option]} (≈${formatMoney(saving, found.currency, true)}/month saving)`
    : `${candidate.meter} – commit to a reservation or savings plan`;
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

const BUDGET_STATUS: Record<Budget['status'], string> = {
  over: 'Over budget last month',
  'forecast-over': 'Forecast over budget this month',
  within: 'Within budget',
};

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${value}%`;
}

function GrowthTable({ title, rows, currency, kind }: {
  title: string; rows: Growth[]; currency: string | null; kind: 'service' | 'subscription';
}) {
  if (!rows.length) return null;
  return (
    <section className="card azure-cost-card">
      <h3>{title}</h3>
      <p className="text-muted azure-cost-note">The last three closed months against the three before, by the monthly average.</p>
      <table className="azure-cost-table">
        <thead><tr><th>Name</th><th>Monthly now</th><th>Monthly before</th><th>Change</th><th>Change %</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.name}>
              <td><DrillLink kind={kind} name={row.name} /></td>
              <td>{formatMoney(row.monthly_now, currency)}</td>
              <td>{formatMoney(row.monthly_before, currency)}</td>
              <td>+{formatMoney(row.change, currency)}</td>
              <td>{row.change_pct == null ? 'new' : `+${row.change_pct}%`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** Paying less for the same consumption: how much of it commitments cover, what
 *  runs on demand steadily enough to commit, what was bought, what is growing,
 *  and the budget. The same findings in both views -- none of it is internal. */
export function FinOpsTab({ customerId, syncedVersion, view, accounts }: {
  customerId: string; syncedVersion: number; view: View; accounts?: string[];
}) {
  const drill = useDrillOpener();
  const [found, setFound] = useState<FinOps | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFinOps(customerId, accounts).then((result) => { setFound(result); setError(null); },
      (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, syncedVersion, accounts?.join(',')]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!found) return <Loading />;
  if (!found.has_meters) {
    return <p className="empty-state">No meter detail synced for this customer yet. Sync it to see FinOps.</p>;
  }

  const currency = found.currency;
  const latest = found.coverage.latest;
  const budget = found.budget;
  return (
    <>
      <div className="azure-cost-kpis">
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Commitment coverage</span>
          <strong>{percent(latest?.coverage_pct)}</strong>
          <span className="azure-cost-kpi-detail">{latest ? `of reservable spend, ${formatMonth(latest.month)}` : 'amortized detail syncing'}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">On demand, reservable</span>
          <strong>{latest ? formatMoney(latest.on_demand, currency) : '—'}</strong>
          <span className="azure-cost-kpi-detail">{latest ? 'that month' : ''}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Steady on demand</span>
          <strong>{formatMoney(found.candidates_monthly, currency)}</strong>
          <span className="azure-cost-kpi-detail">a month, across {found.candidates.length} meter{found.candidates.length === 1 ? '' : 's'}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Estimated saving</span>
          <strong>{found.savings_monthly.ri_3y ? `${formatMoney(found.savings_monthly.ri_3y, currency)}` : '—'}</strong>
          <span className="azure-cost-kpi-detail">
            {found.savings_monthly.ri_3y
              ? `a month on 3-year reservations · ${formatMoney(found.savings_monthly.sp_1y ?? 0, currency)} on a 1-year savings plan`
              : 'prices arrive with the next sync'}
          </span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Monthly budget</span>
          <strong>{budget ? formatMoney(budget.amount, currency) : '—'}</strong>
          <span className="azure-cost-kpi-detail">{budget ? BUDGET_STATUS[budget.status] : 'no MACC, no budget set'}</span></div>
      </div>

      <section className="card azure-cost-card">
        <h3>Commitment coverage by month</h3>
        <p className="text-muted azure-cost-note">
          The share of reservable spend — virtual machines, GPUs, Azure OpenAI, and anything this customer has reserved —
          under a reservation or savings plan, amortized. Closed months only.
        </p>
        {found.coverage.months.length ? (
          <SeriesChart label="Commitment coverage" currency={currency} height={280} onPick={drill ? (month) => drill('month', month) : undefined}
                       categories={found.coverage.months.map((month) => month.month)}
                       categoryLabel={(month) => formatMonth(month, true)}
                       series={[{ name: 'Covered by commitments', data: found.coverage.months.map((month) => month.covered), stack: 'c', color: 0 },
                         { name: 'On demand', data: found.coverage.months.map((month) => month.on_demand), stack: 'c', color: 'other' }]} />
        ) : <p className="text-muted">The amortized meter detail arrives with the next sync.</p>}
        {latest ? (
          <table className="azure-cost-table">
            <thead><tr><th>Family, {formatMonth(latest.month)}</th><th>Covered</th><th>On demand</th><th>Coverage</th></tr></thead>
            <tbody>
              {latest.families.map((family) => (
                <tr key={family.family}>
                  <td>{family.family}</td>
                  <td>{formatMoney(family.covered, currency)}</td>
                  <td>{formatMoney(family.on_demand, currency)}</td>
                  <td>{percent(family.coverage_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      <section className="card azure-cost-card">
        <h3>Steady on-demand candidates</h3>
        <p className="text-muted azure-cost-note">
          On demand in each of the last six closed months, at least $1,000 a month, varying no more than 25% — where a
          reservation or savings plan pays. Savings are estimates: each VM or GPU series priced at the average discount
          across its sizes in {found.pricing_region}, from Azure's public price list; a Windows meter saves on compute
          only. Databases, storage and capacities are not priced yet.
        </p>
        {found.candidates.length ? (
          <table className="azure-cost-table">
            <thead><tr><th>Meter</th><th>Family</th><th>On demand / month</th><th>Variation</th>
              {SHOWN_OPTIONS.map((option) => <th key={option}>Save / month, {OPTION_LABELS[option]}</th>)}
              {view === 'account' ? <th /> : null}</tr></thead>
            <tbody>
              {found.candidates.map((candidate) => (
                <tr key={candidate.meter}>
                  <td>{candidate.meter}</td>
                  <td>{candidate.family}</td>
                  <td>{formatMoney(candidate.monthly_on_demand, currency)}</td>
                  <td>{candidate.variation_pct}%</td>
                  {candidate.savings ? SHOWN_OPTIONS.map((option) => (
                    <td key={option}>{candidate.savings?.[option] != null ? formatMoney(candidate.savings[option]!, currency) : 'not offered'}</td>
                  )) : <td colSpan={SHOWN_OPTIONS.length} className="text-muted">{candidate.not_priced}</td>}
                  {view === 'account' ? <td><CreateOpportunity found={found} candidate={candidate} /></td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-muted">Nothing ran on demand at a steady level for the last six months.</p>}
      </section>

      {found.purchases.length ? (
        <section className="card azure-cost-card">
          <h3>Commitments bought up front</h3>
          <table className="azure-cost-table">
            <thead><tr><th>Month</th><th>Charged</th><th>Amortized</th><th>Bought up front</th></tr></thead>
            <tbody>
              {found.purchases.map((purchase) => (
                <tr key={purchase.month}>
                  <td>{formatMonth(purchase.month)}</td>
                  <td>{formatMoney(purchase.charged, currency)}</td>
                  <td>{formatMoney(purchase.amortized, currency)}</td>
                  <td>{formatMoney(purchase.bought_up_front, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <GrowthTable title="Fastest-growing services" rows={found.growth.services} currency={currency} kind="service" />
      <GrowthTable title="Fastest-growing subscriptions" rows={found.growth.subscriptions} currency={currency} kind="subscription" />

      {budget ? (
        <section className="card azure-cost-card">
          <h3>Budget</h3>
          <dl className="azure-cost-facts">
            <dt>Monthly budget</dt><dd>{formatMoney(budget.amount, currency)}</dd>
            <dt>From</dt><dd>{budget.source === 'set' ? 'set in Settings' : `the MACC spread over its ${budget.term_months} months`}</dd>
            {budget.last_month ? <><dt>{formatMonth(budget.last_month)}</dt><dd>{formatMoney(budget.last_month_actual ?? 0, currency)}</dd></> : null}
            {budget.current_month_forecast != null ? <><dt>This month, forecast</dt><dd>{formatMoney(budget.current_month_forecast, currency)}</dd></> : null}
            <dt>Months over budget, last 12</dt><dd>{budget.over_in_last_12.length}</dd>
            <dt>Status</dt><dd>{BUDGET_STATUS[budget.status]}</dd>
          </dl>
        </section>
      ) : null}
    </>
  );
}
