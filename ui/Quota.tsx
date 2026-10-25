import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useRememberedState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import {
  fetchCustomerQuota, fetchQuota, reportExportPath, saveQuotaSettings,
  type CustomerQuota, type Measure, type QuotaAcross, type QuotaSettings,
} from './client';
import { PopupRow } from './Popup';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink } from './ReportsHome';
import { Loading } from './Loading';

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December'];

function money(value: number | null | undefined, currency: string | null = 'USD'): string {
  return value == null ? '—' : formatMoney(value, currency, true);
}

function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${value}%`;
}

function Kpi({ label, value, detail }: { label: string; value: string; detail?: string | null }) {
  return (
    <div className="azure-cost-kpi card">
      <span className="azure-cost-kpi-label">{label}</span>
      <strong>{value}</strong>
      {detail ? <span className="azure-cost-kpi-detail">{detail}</span> : null}
    </div>
  );
}

function describe(settings: QuotaSettings): string {
  return `${settings.fy}: ${formatMonth(settings.fy_first)} to ${formatMonth(settings.fy_last)}`
    + `${settings.period_is_default ? ' (the fiscal year)' : ''}. Baseline: the monthly `
    + `average of ${formatMonth(settings.baseline_start)} to ${formatMonth(settings.baseline_last)}`
    + `${settings.baseline_is_default ? ' (the default: the months before the period)' : ''}.`;
}

/** The Marketplace and credits filters, as the customer report's toolbar has them. */
function MeasureFilters({ measure, onChange }: { measure: Measure; onChange: (next: Measure) => void }) {
  return (
    <>
      <label className="azure-cost-check" title="Core42's only: the line and what is above it are Core42 revenue">
        Marketplace{' '}
        <select value={String(measure.marketplace)}
                onChange={(event) => onChange({ ...measure,
                  marketplace: event.target.value === 'core42' ? 'core42' : event.target.value === 'true' })}>
          <option value="true">All (MACC consumed)</option>
          <option value="core42">Core42's only (Core42 revenue)</option>
          <option value="false">None</option>
        </select>
      </label>
      <label className="azure-cost-check">
        <input type="checkbox" checked={measure.credits} onChange={(event) => onChange({ ...measure, credits: event.target.checked })} />
        Subtract credits
      </label>
    </>
  );
}

/** One customer's fiscal year against the baseline (operator, 2026-10-22): what
 *  it added above the line so far, where the year lands, and the pipeline's plan
 *  against what happened. */
export function QuotaTab({ customerId, measure, accounts }: { customerId: string; measure: Measure; accounts?: string[] }) {
  const [found, setFound] = useState<CustomerQuota | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCustomerQuota(customerId, measure, accounts).then((result) => { setFound(result); setError(null); },
      (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, measure, accounts?.join(',')]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!found) return <Loading />;
  const currency = found.currency;
  const rows = found.months;
  const against = found.pipeline;
  return (
    <>
      <p className="text-muted azure-cost-note">{describe(found.settings)} Counted net: a month under the line takes away.{' '}
        <Link to="/azure-cost-manager/quota">Set the baseline and quota</Link>.</p>
      <div className="azure-cost-kpis">
        <Kpi label="Baseline, a month" value={money(found.baseline, currency)}
             detail={found.baseline_covered < found.settings.baseline_months
               ? `${found.baseline_covered} of ${found.settings.baseline_months} months synced` : null} />
        <Kpi label="Above the line, to date" value={money(found.above_to_date, currency)} />
        <Kpi label={`Projected, ${found.settings.fy}`} value={money(found.above_projected, currency)} />
        <Kpi label="With pipeline" value={money(found.above_with_pipeline, currency)} />
      </div>
      <section className="card azure-cost-card azure-cost-wide">
        <h3>{found.settings.fy}, month by month</h3>
        <SeriesChart label="Consumption against the baseline" currency={currency} height={300}
                     categories={rows.map((row) => row.month)} categoryLabel={(month) => formatMonth(month, true)}
                     series={[
                       { name: 'Actual', stack: 'month', data: rows.map((row) => (row.kind === 'actual' ? row.consumption : null)), color: 0 },
                       { name: 'Forecast', stack: 'month', data: rows.map((row) => (row.kind === 'forecast' ? row.consumption : null)), color: 1 },
                       { name: 'Pipeline', stack: 'month', data: rows.map((row) => row.pipeline || null), color: 2 },
                       { name: 'Baseline', kind: 'line', dashed: true, data: rows.map((row) => row.baseline), color: 'other' },
                     ]} />
        <table className="azure-cost-table">
          <thead><tr><th>Month</th><th /><th>Consumption</th><th>Above the line</th><th>Pipeline</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.month}>
                <td>{formatMonth(row.month)}</td>
                <td className="text-muted">{row.kind}</td>
                <td>{money(row.consumption, currency)}</td>
                <td className={row.above < 0 ? 'azure-cost-warning' : undefined}>{money(row.above, currency)}</td>
                <td>{row.pipeline ? money(row.pipeline, currency) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card azure-cost-card">
        <h3>Pipeline against what happened</h3>
        {!found.pipeline_available ? <p className="text-muted">No pipeline source.</p>
          : !against.opportunities.length ? (
            <p className="text-muted">No Open or Won opportunity planned consumption for {found.settings.fy}'s closed months.</p>
          ) : (
            <>
              <p className={against.behind ? 'azure-cost-warning' : 'text-muted'}>
                Planned for the closed months: {money(against.planned_to_date, currency)}; added above the line:{' '}
                {money(against.achieved_to_date, currency)}
                {against.behind ? ` — ${money(-against.gap, currency)} behind the plan.` : ' — the plan was met.'}
              </p>
              <table className="azure-cost-table">
                <thead><tr><th>Opportunity</th><th>Status</th><th>Stage</th><th>Planned from</th><th>Planned to date</th></tr></thead>
                <tbody>
                  {against.opportunities.map((item) => (
                    <tr key={item.id ?? item.title}>
                      <td>{item.route ? <Link to={item.route}>{item.title}</Link> : item.title}</td>
                      <td>{item.status}</td><td>{item.stage}</td>
                      <td>{formatMonth(item.first_month)}</td><td>{money(item.planned_to_date, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
      </section>
    </>
  );
}

function SettingsBar({ settings, onSaved }: { settings: QuotaSettings; onSaved: (next: QuotaSettings) => void }) {
  const [draft, setDraft] = useState({
    quota: settings.quota != null ? String(settings.quota) : '', start: settings.baseline_start,
    months: String(settings.baseline_months), fy: String(settings.fy_start_month),
    from: settings.fy_first, to: settings.fy_last,
  });
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  function save() {
    setSaving(true);
    // A period that is just the fiscal year is stored as none, so it moves with the year.
    const period = settings.period_is_default && draft.from === settings.fy_first && draft.to === settings.fy_last
      ? {} : { period_first: draft.from || null, period_last: draft.to || null };
    saveQuotaSettings({ quota: draft.quota.trim() ? Number(draft.quota) : null, baseline_start: draft.start || null,
      baseline_months: Number(draft.months), fy_start_month: Number(draft.fy), ...period })
      .then((next) => { setProblem(null); onSaved(next); }, (failure) => setProblem(errorText(failure)))
      .finally(() => setSaving(false));
  }
  return (
    <section className="card azure-cost-card">
      <h3>Baseline and quota</h3>
      <div className="azure-cost-toolbar">
        <label className="field-labeled">Quota, {settings.fy} (USD)
          <input type="number" min="0" step="100000" value={draft.quota} placeholder="not set"
                 onChange={(event) => setDraft({ ...draft, quota: event.target.value })} />
        </label>
        <label className="field-labeled">Quota period from
          <input type="month" value={draft.from} onChange={(event) => setDraft({ ...draft, from: event.target.value })} />
        </label>
        <label className="field-labeled">to
          <input type="month" value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} />
        </label>
        <label className="field-labeled">Fiscal year starts in
          <select value={draft.fy} onChange={(event) => setDraft({ ...draft, fy: event.target.value })}>
            {MONTH_NAMES.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
          </select>
        </label>
        <label className="field-labeled">Baseline from
          <input type="month" value={draft.start} onChange={(event) => setDraft({ ...draft, start: event.target.value })} />
        </label>
        <label className="field-labeled">for months
          <input type="number" min="1" max="24" value={draft.months}
                 onChange={(event) => setDraft({ ...draft, months: event.target.value })} />
        </label>
        <button type="button" className="btn" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button>
        {!settings.period_is_default ? (
          <button type="button" className="btn azure-cost-link-button"
                  onClick={() => saveQuotaSettings({ period_first: null, period_last: null }).then(onSaved, (failure) => setProblem(errorText(failure)))}>
            Use the fiscal year</button>
        ) : null}
        {!settings.baseline_is_default ? (
          <button type="button" className="btn azure-cost-link-button"
                  onClick={() => saveQuotaSettings({ baseline_start: null }).then(onSaved, (failure) => setProblem(errorText(failure)))}>
            Use the default baseline</button>
        ) : null}
      </div>
      {problem ? <div className="azure-cost-error">{problem}</div> : null}
      <p className="text-muted azure-cost-note">{describe(settings)} One baseline for every customer.</p>
    </section>
  );
}

/** Every customer above the baseline, and the quota's attainment (operator, 2026-10-22). */
export function QuotaPage() {
  const [report, setReport] = useState<QuotaAcross | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  // Its own, Core42 revenue by default: quota counts Core42's revenue, not MACC consumption
  // (operator, 2026-10-25) -- while the customer reports keep MACC consumed as theirs.
  const [measure, setMeasure] = useRememberedState<Measure>('azure-cost-manager.quota-measure', { marketplace: 'core42', credits: true });

  useEffect(() => {
    setReport(null);
    fetchQuota(measure).then(setReport, (failure) => setError(errorText(failure)));
  }, [measure, version]);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Baseline and quota' }]} />
      <header className="azure-cost-header">
        <h1>Baseline and quota</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('quota', measure))}>Export to Excel</a>
      </header>
      <div className="azure-cost-toolbar"><MeasureFilters measure={measure} onChange={setMeasure} /></div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!report ? <p className="text-muted">Working out every customer's year… this takes a little while.</p> : (
        <>
          <SettingsBar key={JSON.stringify(report.settings)} settings={report.settings} onSaved={() => setVersion((n) => n + 1)} />
          <div className="azure-cost-kpis">
            <Kpi label={`Quota, ${report.settings.fy}`} value={money(report.settings.quota)} />
            <Kpi label="Above the line, to date" value={money(report.above_to_date)} detail={report.attained_pct != null ? `${pct(report.attained_pct)} of quota` : null} />
            <Kpi label="Projected" value={money(report.above_projected)} detail={report.projected_pct != null ? `${pct(report.projected_pct)} of quota` : null} />
            <Kpi label="With pipeline" value={money(report.above_with_pipeline)} detail={report.with_pipeline_pct != null ? `${pct(report.with_pipeline_pct)} of quota` : null} />
            <Kpi label="Gap to quota" value={money(report.gap_to_quota)} detail="against the projection" />
          </div>
          <section className="card azure-cost-card">
            <h3>By customer</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Customer</th><th>Baseline a month</th><th>Above, to date</th><th>Projected</th><th>With pipeline</th>
                <th>Pipeline planned to date</th></tr></thead>
              <tbody>
                {report.customers.map((row) => (
                  <Fragment key={row.id}>
                    <tr>
                      <td>
                        {row.missed.length ? (
                          <button type="button" className="btn azure-cost-link-button" aria-expanded={open === row.id}
                                  onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? '▾' : '▸'}</button>
                        ) : null}{' '}
                        <Link to={reportLink('Quota', row.id)}>{row.name}</Link>
                        {row.affiliates ? <span className="text-muted"> + {row.affiliates}</span> : null}
                      </td>
                      <td>{money(row.baseline, row.currency)}</td>
                      <td className={row.above_to_date < 0 ? 'azure-cost-warning' : undefined}>{money(row.above_to_date, row.currency)}</td>
                      <td>{money(row.above_projected, row.currency)}</td>
                      <td>{money(row.above_with_pipeline, row.currency)}</td>
                      <td>{row.pipeline.planned_to_date ? (
                        <span className={row.pipeline.behind ? 'azure-cost-warning' : undefined}>
                          {money(row.pipeline.planned_to_date, row.currency)}{row.pipeline.behind ? ' (behind)' : ''}</span>
                      ) : ''}</td>
                    </tr>
                    {open === row.id ? (
                      <PopupRow kicker="Missed forecasts" title={row.name} onClose={() => setOpen(null)}>
                        <h4>Opportunities that planned more than happened</h4>
                        <ul>{row.missed.map((item) => (
                          <li key={item.id ?? item.title}>{item.route ? <Link to={item.route}>{item.title}</Link> : item.title}
                            {' '}— {item.status}, {item.stage}: {money(item.planned_to_date, row.currency)} planned from{' '}
                            {formatMonth(item.first_month)}</li>))}</ul>
                      </PopupRow>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
