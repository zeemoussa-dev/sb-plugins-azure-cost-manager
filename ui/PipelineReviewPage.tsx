import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import { fetchPipelineReview, type PipelineReview, type ReviewChecked, type ReviewRow } from './client';
import { useRememberedFold } from './CompassText';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

const STAGE_ORDER = ['Identified', 'Qualified', 'Proposed', 'Committed', 'Closed', 'Won'];
const VERDICTS: { key: ReviewChecked['verdict']; label: string }[] = [
  { key: 'landed', label: 'Landed' }, { key: 'over', label: 'Over' }, { key: 'short', label: 'Short' },
  { key: 'late', label: 'Late' }, { key: 'no scope', label: 'No scope' }, { key: 'no trend', label: 'No trend' },
];
const GAP_LABELS: Record<string, string> = {
  customers_without_account_manager: 'Customers with no account manager',
  opportunities_without_start: 'Opportunities with no start',
  opportunities_without_amount: 'Opportunities with no amount or plan',
  opportunities_unscoped: 'Opportunities with no technologies (no scope: their impact cannot be counted)',
};

const money = (value: number | null | undefined) => (value == null ? '—' : formatMoney(value, 'USD', true));
const percent = (value: number | null | undefined) => (value == null ? '—' : `${Math.round(value * 100)}%`);

function Note({ stem, title }: { stem: string | null; title: string }) {
  return stem ? <Link to={`/browse/${encodeURIComponent(stem)}`}>{title}</Link> : <>{title}</>;
}

function Verdicts({ counts }: { counts: Record<string, number> }) {
  const shown = VERDICTS.filter(({ key }) => counts[key]);
  return shown.length ? <>{shown.map(({ key, label }) => `${counts[key]} ${label.toLowerCase()}`).join(' · ')}</> : <>—</>;
}

function Rollup({ rows, level, onDrill }: { rows: ReviewRow[]; level: string; onDrill: (level: string) => void }) {
  const kind = level.split(':')[0];
  const first = kind === 'all' ? 'Account manager' : kind === 'customer' ? 'Opportunity' : 'Customer';
  return (
    <table className="azure-cost-table">
      <thead><tr><th>{first}</th><th>Opportunities</th><th>Next 12 months, raw</th><th>Weighted</th>
        <th>Planned vs actual</th><th>Plan accuracy</th><th>Months slipped</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key || row.label}>
            <td>{row.drill ? <button type="button" className="azure-cost-link-button" onClick={() => onDrill(row.drill!)}>{row.label}</button>
              : <Note stem={row.stem} title={row.label} />}</td>
            <td>{row.opportunities}</td>
            <td>{money(row.raw)}</td>
            <td>{money(row.weighted)}</td>
            <td className="text-muted"><Verdicts counts={row.verdicts} /></td>
            <td>{percent(row.accuracy)}</td>
            <td>{row.slipped_months || '—'}</td>
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
        <span className="text-muted">{filled.map(([key, items]) => `${items.length} ${GAP_LABELS[key]?.split(' (')[0].toLowerCase() ?? key}`).join(' · ')}</span>
      </summary>
      <p className="text-muted azure-cost-note">Fix these in the vault notes; the next snapshot picks them up.</p>
      {filled.map(([key, items]) => (
        <div key={key}><h4>{GAP_LABELS[key] ?? key}</h4><p className="text-muted">{items.join(' · ')}</p></div>
      ))}
    </details>
  );
}

/** The weekly pipeline review (PLAN.md, release 2): what changed this week, when the
 *  pipeline lands, and whether what was planned landed -- for all customers, an account
 *  manager, a segment, a PSS or one customer. Everyone sees every level. */
export function PipelineReviewPage() {
  const [level, setLevel] = useUrlState<string>('level', 'all');
  const [week, setWeek] = useUrlState<string>('week', '');
  const [found, setFound] = useState<PipelineReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [weighted, setWeighted] = useState(true);

  useEffect(() => {
    setFound(null); setError(null);
    fetchPipelineReview(level, week || undefined).then(setFound, (failure) => setError(errorText(failure)));
  }, [level, week]);

  const months = found ? Object.keys(found.landing.months).sort() : [];
  const stages = found ? STAGE_ORDER.filter((stage) => months.some((month) => found.landing.months[month].by_stage[stage])) : [];
  const checked = found?.planned_vs_actual;
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Pipeline review' }]} />
      <header className="azure-cost-header">
        <h1>Pipeline review{found && level !== 'all' ? `: ${found.label}` : ''}</h1>
      </header>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!found ? (error ? null : <Loading label="Reading the week's snapshot and what each opportunity added…" />) : (
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
            <label className="field-labeled">Week ending
              <select value={week || found.week_end} onChange={(event) => setWeek(event.target.value)}>
                {[...found.weeks].reverse().map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            {level !== 'all' ? <button type="button" className="btn" onClick={() => setLevel('all')}>All customers</button> : null}
          </div>
          <p className="text-muted azure-cost-note">
            Snapshot of the week ending {found.week_end}{found.taken_late ? `, taken late (${(found.taken_at ?? '').slice(0, 10)})` : ''}.
            {' '}{found.opportunities} open, won and other opportunities at this level. Weights:
            {' '}{Object.entries(found.settings.stage_weights).map(([stage, weight]) => `${stage} ${Math.round(weight * 100)}%`).join(', ')}.
          </p>

          <div className="azure-cost-kpis">
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Weighted pipeline</span>
              <strong>{money(found.landing.weighted)}</strong>
              <span className="azure-cost-kpi-detail">next {found.settings.horizon_months} months · {money(found.landing.raw)} raw</span></div>
            {found.landing.coverage ? (
              <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Coverage of the quota gap</span>
                <strong>{found.landing.coverage.ratio == null ? '—' : `${found.landing.coverage.ratio}×`}</strong>
                <span className="azure-cost-kpi-detail">{money(found.landing.coverage.weighted_in_period)} weighted against
                  {' '}{money(found.landing.coverage.gap_to_quota)} to go{found.landing.coverage.period_last ? ` by ${formatMonth(found.landing.coverage.period_last, true)}` : ''}</span></div>
            ) : null}
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">This week</span>
              <strong>{found.movement.changes.length}</strong>
              <span className="azure-cost-kpi-detail">{found.movement.first_snapshot ? 'first snapshot: opened this week' : `changes since ${found.movement.compared_with}`}</span></div>
            <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Plan accuracy</span>
              <strong>{percent(checked?.accuracy)}</strong>
              <span className="azure-cost-kpi-detail">{checked ? <Verdicts counts={checked.counts} /> : null}</span></div>
          </div>

          <section className="card azure-cost-card">
            <h3>{level === 'all' ? 'By account manager' : level.startsWith('customer:') ? 'Opportunities' : 'By customer'}</h3>
            <Rollup rows={found.rollup} level={level} onDrill={setLevel} />
          </section>

          <section className="card azure-cost-card">
            <h3>This week</h3>
            {found.movement.first_snapshot ? (
              <p className="text-muted azure-cost-note">This is the first snapshot, so there is no last week to compare with: shown are the
                opportunities opened during the week. From next week, every new, won, lost, re-staged, slipped and re-sized one shows here.</p>
            ) : null}
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
            ) : <p className="text-muted">Nothing changed this week.</p>}
          </section>

          <section className="card azure-cost-card">
            <div className="azure-cost-card-head">
              <h3>When it lands</h3>
              <label className="azure-cost-checkbox"><input type="checkbox" checked={weighted} onChange={(event) => setWeighted(event.target.checked)} /> Weighted by stage</label>
            </div>
            <SeriesChart label="Pipeline by month" currency="USD" height={300}
                         categories={months} categoryLabel={(month) => formatMonth(month, true)}
                         series={[
                           ...stages.map((stage, index) => ({
                             name: stage, stack: 'p', color: index,
                             data: months.map((month) => {
                               const value = found.landing.months[month].by_stage[stage] ?? 0;
                               const weight = stage === 'Won' ? found.settings.won_weight : found.settings.stage_weights[stage] ?? 0;
                               return (weighted ? value * weight : value) || null;
                             }),
                           })),
                         ]} />
            <p className="text-muted azure-cost-note">Each open or won opportunity's plan by month, from the month of the snapshot; its stage's weight applied when weighted.</p>
          </section>

          <section className="card azure-cost-card">
            <h3>Planned against what landed</h3>
            <p className="text-muted azure-cost-note">
              Each opportunity whose consumption has started: its plan in the closed months against what it added above its
              natural trend, frozen before it could move anything. Within ±{found.settings.tolerance_pct}% is landed. One with no technologies
              has no scope and is not measured: a whole customer's swings (a licence purchase, a migration) are not its doing. Estimated
              means the trend was fitted from history after the fact.
            </p>
            {checked && checked.rows.length ? (
              <table className="azure-cost-table">
                <thead><tr><th>Opportunity</th><th>Customer</th><th>Account manager</th><th>Months</th><th>Planned</th><th>Added</th><th>Verdict</th><th>Against</th></tr></thead>
                <tbody>
                  {checked.rows.map((row) => (
                    <tr key={row.id}>
                      <td><Note stem={row.stem} title={row.title} /></td>
                      <td>{row.customer}</td>
                      <td>{row.account_manager ?? '—'}</td>
                      <td className="text-muted">{row.months.length ? `${formatMonth(row.months[0], true)}–${formatMonth(row.months[row.months.length - 1], true)}` : '—'}</td>
                      <td>{money(row.planned)}</td>
                      <td>{money(row.added)}</td>
                      <td className={row.verdict === 'short' || row.verdict === 'late' ? 'azure-cost-warning' : undefined}>{row.verdict}</td>
                      <td className="text-muted">{row.against}{row.estimated ? ' · estimated' : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="text-muted">No opportunity at this level has started consuming yet.</p>}
          </section>

          <Gaps gaps={found.gaps} />
        </>
      )}
    </div>
  );
}
