import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import { fetchPipelineReview, type GrowthRow, type PipelineReview, type ReviewRow } from './client';
import { useRememberedFold } from './CompassText';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

const STAGE_ORDER = ['Identified', 'Qualified', 'Proposed', 'Committed', 'Closed', 'Won'];
const GAP_LABELS: Record<string, string> = {
  customers_without_account_manager: 'Customers with no account manager',
  opportunities_without_start: 'Opportunities with no start',
  opportunities_without_amount: 'Opportunities with no amount or plan',
};
const WARNED = new Set(['short', 'not growing']);

const money = (value: number | null | undefined) => (value == null ? '—' : formatMoney(value, 'USD', true));

function Note({ stem, title }: { stem: string | null; title: string }) {
  return stem ? <Link to={`/browse/${encodeURIComponent(stem)}`}>{title}</Link> : <>{title}</>;
}

function Verdict({ value }: { value: string | null }) {
  return value ? <span className={WARNED.has(value) ? 'azure-cost-warning' : undefined}>{value}</span> : <>—</>;
}

function Rollup({ rows, level, onDrill }: { rows: ReviewRow[]; level: string; onDrill: (level: string) => void }) {
  const kind = level.split(':')[0];
  const byOpportunity = kind === 'customer';
  const first = kind === 'all' ? 'Account manager' : byOpportunity ? 'Opportunity' : 'Customer';
  return (
    <table className="azure-cost-table">
      <thead><tr><th>{first}</th>{byOpportunity ? <th>Stage</th> : <th>Opportunities</th>}<th>Planned, period</th><th>Weighted</th>
        <th>Planned to date</th>{byOpportunity ? null : <><th>Growth to date</th><th>Plan vs growth</th><th>Growth, period</th><th>Azure forecast, rest of period</th></>}
        <th>Months slipped</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key || row.label}>
            <td>{row.drill ? <button type="button" className="azure-cost-link-button" onClick={() => onDrill(row.drill!)}>{row.label}</button>
              : <Note stem={row.stem} title={row.label} />}</td>
            <td>{byOpportunity ? `${row.stage ?? '—'}${row.status && row.status !== 'Open' ? ` · ${row.status}` : ''}` : row.opportunities}</td>
            <td>{money(row.planned_period)}</td>
            <td>{money(row.weighted_period)}</td>
            <td>{money(row.planned_to_date)}</td>
            {byOpportunity ? null : <><td>{money(row.growth_to_date)}</td><td><Verdict value={row.verdict} /></td><td>{money(row.growth_period)}</td>
              <td>{money(row.forecast_ahead ?? null)}</td></>}
            <td>{row.slipped_months || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CustomerMonths({ row, closed }: { row: GrowthRow; closed: Set<string> }) {
  return (
    <table className="azure-cost-table">
      <thead><tr><th>Month</th><th>Growth above baseline</th><th>Planned</th><th>Weighted</th></tr></thead>
      <tbody>
        {row.months.map((month) => (
          <tr key={month.month}>
            <td>{formatMonth(month.month, true)}{closed.has(month.month) ? '' : <span className="text-muted"> · forecast</span>}</td>
            <td>{money(month.growth)}</td>
            <td>{money(month.planned)}</td>
            <td>{money(month.weighted)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Gaps({ gaps }: { gaps: Record<string, string[]> }) {
  const [open, fold] = useRememberedFold('azure-cost-manager.pipeline-gaps-folded');
  const filled = Object.entries(gaps).filter(([, items]) => items.length);
  if (!filled.length) return null;
  return (
    <details className="card azure-cost-card azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head"><h3>What weakens this review</h3>
        <span className="text-muted">{filled.map(([key, items]) => `${items.length} ${(GAP_LABELS[key] ?? key).toLowerCase()}`).join(' · ')}</span>
      </summary>
      <p className="text-muted azure-cost-note">Fix these in the vault notes; the review picks them up the next time it is opened.</p>
      {filled.map(([key, items]) => (
        <div key={key}><h4>{GAP_LABELS[key] ?? key}</h4><p className="text-muted">{items.join(' · ')}</p></div>
      ))}
    </details>
  );
}

/** The monthly pipeline review (PLAN.md; operator, 2026-10-25): what changed this month,
 *  and over the quota period -- months gone included, they count -- each customer's
 *  opportunities against its growth above the quota baseline. For all customers, an
 *  account manager, a segment, a PSS or one customer; everyone sees every level. */
export function PipelineReviewPage() {
  const [level, setLevel] = useUrlState<string>('level', 'all');
  const [month, setMonth] = useUrlState<string>('month', '');
  const [found, setFound] = useState<PipelineReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [weighted, setWeighted] = useState(false);

  useEffect(() => {
    setFound(null); setError(null);
    fetchPipelineReview(level, month || undefined).then(setFound, (failure) => setError(errorText(failure)));
  }, [level, month]);

  const span = found?.period.months ?? [];
  const closed = new Set(found?.period.closed ?? []);
  const lastClosed = [...closed].sort().pop();
  const stages = found ? STAGE_ORDER.filter((stage) => span.some((m) => found.landing.months[m]?.by_stage[stage])) : [];
  const growth = found?.growth;
  const single = level.startsWith('customer:') ? growth?.rows[0] : undefined;
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Pipeline review' }]} />
      <header className="azure-cost-header">
        <h1>Pipeline review{found && level !== 'all' ? `: ${found.label}` : ''}</h1>
      </header>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!found || !growth ? (error ? null : <Loading label="Reading the month's pipeline and each customer's growth above its baseline…" />) : (
        <>
          <div className="azure-cost-toolbar">
            <label className="field-labeled">Showing
              <select value={level} onChange={(event) => setLevel(event.target.value)}>
                <option value="all">All customers</option>
                <optgroup label="Account managers">
                  {found.levels.managers.map((row) => <option key={row.level} value={row.level}>{row.name} ({row.customers})</option>)}
                </optgroup>
                <optgroup label="Segments">
                  {found.levels.segments.map((name) => <option key={name} value={`segment:${name}`}>{name}</option>)}
                </optgroup>
                <optgroup label="PSS">
                  {found.levels.pss.map((row) => <option key={row.level} value={row.level}>{row.name}</option>)}
                </optgroup>
                <optgroup label="Customers">
                  {found.levels.customers.map((row) => <option key={row.level} value={row.level}>{row.name}</option>)}
                </optgroup>
              </select>
            </label>
            <label className="field-labeled">Month
              <select value={month || found.month} onChange={(event) => setMonth(event.target.value)}>
                {[...found.months].reverse().map((value) => <option key={value} value={value}>{formatMonth(value)}</option>)}
              </select>
            </label>
            {level !== 'all' ? <button type="button" className="btn" onClick={() => setLevel('all')}>All customers</button> : null}
          </div>
          <p className="text-muted azure-cost-note">
            {formatMonth(found.month)}{found.live ? ` — live, refreshed ${(found.taken_at ?? '').slice(0, 16).replace('T', ' ')}` : ', as it stood when the month ended'}.
            {' '}Quota period {found.period.label ?? ''} ({formatMonth(found.period.first, true)}–{formatMonth(found.period.last, true)}):
            growth is Core42 revenue — Azure usage and Core42's own Marketplace offers, not third-party Marketplace or SaaS — above
            each customer's quota baseline, actual for the months closed and Azure's usage forecast after.
          </p>

          <div className="azure-cost-kpis">
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Planned in the period</span>
              <strong>{money(growth.planned_period)}</strong>
              <span className="azure-cost-kpi-detail">{money(growth.weighted_period)} weighted by stage · {found.opportunities} opportunities</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Growth to date</span>
              <strong>{money(growth.growth_to_date)}</strong>
              <span className="azure-cost-kpi-detail">against {money(growth.planned_to_date)} planned · <Verdict value={growth.verdict} /></span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Growth in the period</span>
              <strong>{money(growth.growth_period)}</strong>
              <span className="azure-cost-kpi-detail">to date plus the forecast for the rest</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Azure forecast to {formatMonth(found.period.last, true)}</span>
              <strong>{money(growth.forecast_ahead)}</strong>
              <span className="azure-cost-kpi-detail">this month on: {money(growth.growth_ahead)} above baseline against
                {' '}{money(growth.planned_ahead)} planned for the same months</span></div>
            {found.landing.coverage ? (
              <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Coverage of the quota gap</span>
                <strong>{found.landing.coverage.ratio == null ? '—' : `${found.landing.coverage.ratio}×`}</strong>
                <span className="azure-cost-kpi-detail">{money(found.landing.coverage.weighted_ahead)} weighted still to come against
                  {' '}{money(found.landing.coverage.gap_to_quota)} short of the {money(found.landing.coverage.quota)} quota</span></div>
            ) : null}
          </div>

          <section className="card azure-cost-card">
            <div className="azure-cost-card-head">
              <h3>The plan against the growth</h3>
              <label className="azure-cost-checkbox"><input type="checkbox" checked={weighted} onChange={(event) => setWeighted(event.target.checked)} /> Weight the plan by stage</label>
            </div>
            <SeriesChart label="Plan against growth" currency="USD" height={300}
                         categories={span} categoryLabel={(value) => formatMonth(value, true)}
                         series={[
                           ...stages.map((stage, index) => ({
                             name: stage, stack: 'p', color: index,
                             data: span.map((value) => {
                               const amount = found.landing.months[value]?.by_stage[stage] ?? 0;
                               const weight = stage === 'Won' ? found.settings.won_weight : found.settings.stage_weights[stage] ?? 0;
                               return (weighted ? amount * weight : amount) || null;
                             }),
                           })),
                           { name: 'Growth above baseline', kind: 'line' as const, color: 'other' as const,
                             data: span.map((value) => (closed.has(value) ? growth.months[value]?.growth ?? null : null)) },
                           { name: 'Growth, forecast', kind: 'line' as const, color: 'other' as const, dashed: true,
                             // From the last closed month on, so the forecast continues the actual line.
                             data: span.map((value) => (!closed.has(value) || value === lastClosed
                               ? growth.months[value]?.growth ?? null : null)) },
                         ]} />
            <p className="text-muted azure-cost-note">Bars: what the opportunities planned each month, by stage. Lines: how much the customers
              grew above their quota baseline — actual in the months closed, then the automatic forecast.</p>
          </section>

          <section className="card azure-cost-card">
            <h3>{level === 'all' ? 'By account manager' : single ? 'Opportunities' : 'By customer'}</h3>
            <Rollup rows={found.rollup} level={level} onDrill={setLevel} />
          </section>

          {single ? (
            <section className="card azure-cost-card">
              <h3>{single.name}: month by month</h3>
              <p className="text-muted azure-cost-note">Baseline {money(single.baseline)} a month (the quota's). <Verdict value={single.verdict} /> to date.</p>
              <CustomerMonths row={single} closed={closed} />
            </section>
          ) : level !== 'all' ? null : (
            <section className="card azure-cost-card">
              <h3>Customers: plan against growth</h3>
              <p className="text-muted azure-cost-note">Each customer (an affiliate with its own account manager on its own), its plan
                to date against its growth above baseline. Within ±{found.settings.tolerance_pct}% is landed.</p>
              <table className="azure-cost-table">
                <thead><tr><th>Customer</th><th>Account manager</th><th>Planned to date</th><th>Growth to date</th><th>Plan vs growth</th>
                  <th>Planned, period</th><th>Growth, period</th></tr></thead>
                <tbody>
                  {growth.rows.filter((row) => row.planned_period || row.growth_period).map((row) => (
                    <tr key={row.id}>
                      <td><button type="button" className="azure-cost-link-button" onClick={() => setLevel(`customer:${row.id}`)}>{row.name}</button></td>
                      <td>{row.account_manager ?? '—'}</td>
                      <td>{money(row.planned_to_date)}</td>
                      <td>{money(row.growth_to_date)}</td>
                      <td><Verdict value={row.verdict} /></td>
                      <td>{money(row.planned_period)}</td>
                      <td>{money(row.growth_period)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="card azure-cost-card">
            <h3>This month</h3>
            {found.movement.first_snapshot ? (
              <p className="text-muted azure-cost-note">The first month the review has kept, so there is no last month to compare with: shown are the
                opportunities opened this month. From next month, every new, won, lost, re-staged, slipped and re-sized one shows here.</p>
            ) : <p className="text-muted azure-cost-note">Changes since {formatMonth(found.movement.compared_with ?? '')}.</p>}
            {found.movement.changes.length ? (
              <table className="azure-cost-table">
                <thead><tr><th>Change</th><th>Opportunity</th><th>Customer</th><th>Account manager</th><th>What</th><th>A month</th></tr></thead>
                <tbody>
                  {found.movement.changes.map((change) => (
                    <tr key={`${change.kind}|${change.id}`}>
                      <td>{change.kind}</td>
                      <td><Note stem={change.stem} title={change.title} /></td>
                      <td>{change.customer_id ? <button type="button" className="azure-cost-link-button"
                                                        onClick={() => setLevel(`customer:${change.customer_id}`)}>{change.customer}</button> : change.customer}</td>
                      <td>{change.account_manager ?? '—'}</td>
                      <td className="text-muted">{change.detail}</td>
                      <td>{money(change.monthly)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-muted">Nothing changed this month.</p>}
          </section>

          <Gaps gaps={found.gaps} />
        </>
      )}
    </div>
  );
}
