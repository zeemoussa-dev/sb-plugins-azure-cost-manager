import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { NoteText } from '../../pluginHost/noteText';
import { SeriesChart, type Series } from './charts';
import {
  fetchFocus, fetchFocusOptions, fetchKeptFocus,
  type Focus, type FocusOptions, type FocusReport, type FocusRow, type KeptFocus,
} from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';
import { SubscriptionLabel } from './SubscriptionLabel';

const EMPTY: Focus = { groups: [], subscriptions: [], services: [] };
const PICKER_ROWS = 60;

const chosenCount = (focus: Focus) => focus.groups.length + focus.subscriptions.length + focus.services.length;

function Pct({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted">—</span>;
  return <span className={value >= 0 ? 'azure-cost-up' : 'azure-cost-down'}>{value >= 0 ? '▲ +' : '▼ '}{value}%</span>;
}

/** One column of the picker: a filter box and the names to tick. */
function PickList({ title, rows, chosen, onToggle, currency, render }: {
  title: string; rows: { name: string; monthly?: number; note?: string | null }[]; chosen: string[];
  onToggle: (name: string) => void; currency: string | null; render?: (name: string) => ReactNode;
}) {
  const [filter, setFilter] = useState('');
  const shown = rows.filter((row) => chosen.includes(row.name) || row.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <fieldset className="azure-cost-analysis-list">
      <legend>{title}{chosen.length ? ` · ${chosen.length} chosen` : ''}</legend>
      {rows.length > 8 ? (
        <input type="search" placeholder={`Filter ${title.toLowerCase()}`} value={filter} aria-label={`Filter ${title}`}
               onChange={(event) => setFilter(event.target.value)} />
      ) : null}
      <div className="azure-cost-analysis-options">
        {shown.slice(0, PICKER_ROWS).map((row) => (
          <label key={row.name} className="azure-cost-check">
            <input type="checkbox" checked={chosen.includes(row.name)} onChange={() => onToggle(row.name)} />
            <span>{render ? render(row.name) : row.name}</span>
            {row.monthly != null ? <span className="text-muted">{formatMoney(row.monthly, currency, true)}/mo</span> : null}
            {row.note ? <span className="text-muted">· {row.note}</span> : null}
          </label>
        ))}
        {!rows.length ? <p className="text-muted">None.</p> : null}
        {shown.length > PICKER_ROWS ? <p className="text-muted">{shown.length - PICKER_ROWS} more: filter to find them.</p> : null}
      </div>
    </fieldset>
  );
}

function Rows({ rows, kind, currency }: { rows: FocusRow[]; kind: 'service' | 'subscription'; currency: string | null }) {
  return (
    <table className="azure-cost-table">
      <thead><tr><th>{kind === 'service' ? 'Service' : 'Subscription'}</th><th>Last 3 months, monthly</th><th>3 before</th><th>Change</th></tr></thead>
      <tbody>
        {rows.slice(0, 12).map((row) => (
          <tr key={row.name}>
            <td><DrillLink kind={kind} name={row.name} /></td>
            <td>{formatMoney(row.monthly_recent, currency)}</td>
            <td>{formatMoney(row.monthly_before, currency)}</td>
            <td><Pct value={row.change_pct} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Compass's reading of the slice, the four ways the operator asked for. */
function CompassReading({ report, writing, onWrite }: { report: FocusReport; writing: boolean; onWrite: () => void }) {
  const kept = report.answer;
  const answer = kept.value;
  return (
    <section className="card azure-cost-card azure-cost-wide">
      <div className="azure-cost-card-head">
        <h3>Compass's analysis</h3>
        <button type="button" className="btn btn-primary" disabled={writing || !kept.available} onClick={onWrite}
                title={kept.available ? 'Compass reads the figures below with the industry, the tags and what you told it' : 'Compass is not available to plugins on this install'}>
          {answer ? 'Analyse again' : 'Analyse with Compass'}
        </button>
      </div>
      {writing ? <Loading label="Compass is reading the slice: its months, services, meters, tags and the industry…" />
        : !answer ? <p className="text-muted">Not analysed yet. The figures below are the plugin's; Compass reads them{report.industry ? ` with ${report.industry} in mind` : ''}.</p>
          : (
            <>
              {kept.stale ? <p className="azure-cost-warning">The figures have changed since this was written.</p> : null}
              <p><strong>{answer.headline}</strong></p>
              <div className="azure-cost-analysis-answer">
                <div>
                  <h4>The cost story</h4>
                  <NoteText text={answer.cost_story} />
                </div>
                <div>
                  <h4>What the workload is <span className="text-muted">· {answer.architecture.confidence} confidence</span></h4>
                  <p>{answer.architecture.workload}</p>
                  {answer.architecture.evidence.length ? <ul>{answer.architecture.evidence.map((item) => <li key={item}>{item}</li>)}</ul> : null}
                </div>
                <div>
                  <h4>Optimisation</h4>
                  {answer.optimisation.length ? (
                    <ul>{answer.optimisation.map((item) => (
                      <li key={item.move}><strong>{item.move}</strong>: {item.why} <span className="text-muted">Check first: {item.check_first}</span></li>
                    ))}</ul>
                  ) : <p className="text-muted">Nothing to suggest.</p>}
                </div>
                <div>
                  <h4>Growth: what to pitch</h4>
                  {answer.growth.length ? (
                    <ul>{answer.growth.map((item) => <li key={item.pitch}><strong>{item.pitch}</strong>: {item.why}</li>)}</ul>
                  ) : <p className="text-muted">Nothing to suggest.</p>}
                </div>
              </div>
              {answer.questions.length ? (
                <p><span className="azure-cost-kpi-label">Ask the customer</span></p>
              ) : null}
              {answer.questions.length ? <ul>{answer.questions.map((item) => <li key={item}>{item}</li>)}</ul> : null}
              {kept.at ? <p className="text-muted azure-cost-note">Written {new Date(kept.at).toLocaleString()}.</p> : null}
            </>
          )}
    </section>
  );
}

/** Analysis (operator, 2026-10-29): any mix of services, subscriptions and subscription
 *  groups, its figures, and Compass's reading -- cost story, workload, optimisation and
 *  growth -- kept per customer and choice. */
export function AnalysisTab({ customerId, accounts, syncedVersion }: {
  customerId: string; accounts?: string[]; syncedVersion: number;
}) {
  const [options, setOptions] = useState<FocusOptions | null>(null);
  const [kept, setKept] = useState<KeptFocus[]>([]);
  const [focus, setFocus] = useState<Focus>(EMPTY);
  const [report, setReport] = useState<FocusReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accountsKey = accounts?.join(',') ?? '';
  const shown = useMemo(() => (accountsKey ? accountsKey.split(',') : undefined), [accountsKey]);
  const focusKey = JSON.stringify(focus);

  useEffect(() => {
    fetchFocusOptions(customerId, shown).then(setOptions, (failure) => setError(errorText(failure)));
    fetchKeptFocus(customerId).then(setKept, () => setKept([]));
  }, [customerId, shown, syncedVersion]);

  useEffect(() => {
    if (!chosenCount(focus)) { setReport(null); return; }
    setLoading(true);
    fetchFocus(customerId, focus, false, shown)
      .then((found) => { setReport(found); setError(null); }, (failure) => setError(errorText(failure)))
      .finally(() => setLoading(false));
  // `focusKey` stands for `focus`'s contents.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, shown, focusKey, syncedVersion]);

  const toggle = (kind: keyof Focus) => (name: string) => setFocus({
    ...focus, [kind]: focus[kind].includes(name) ? focus[kind].filter((other) => other !== name) : [...focus[kind], name],
  });

  const write = () => {
    setWriting(true); setError(null);
    fetchFocus(customerId, focus, true, shown)
      .then((found) => { setReport(found); fetchKeptFocus(customerId).then(setKept, () => undefined); },
        (failure) => setError(errorText(failure)))
      .finally(() => setWriting(false));
  };

  if (!options) return error ? <div className="azure-cost-error">{error}</div> : <Loading />;
  const currency = report?.currency ?? options.currency;
  const figures = report?.figures;

  return (
    <>
      <section className="card azure-cost-card azure-cost-wide">
        <div className="azure-cost-card-head">
          <h3>What to analyse</h3>
          {chosenCount(focus) ? <button type="button" className="btn" onClick={() => setFocus(EMPTY)}>Clear</button> : null}
        </div>
        {kept.length ? (
          <div className="azure-cost-analysis-kept">
            <span className="azure-cost-kpi-label">Kept analyses</span>
            {kept.map((item) => (
              <button key={`${item.title}|${item.at}`} type="button" className="btn azure-cost-link-button"
                      onClick={() => setFocus(item.focus)} title={`Written ${new Date(item.at).toLocaleString()}`}>
                {item.title}
              </button>
            ))}
          </div>
        ) : null}
        <p className="text-muted azure-cost-note">
          Tick any mix. Subscriptions and groups narrow where; services narrow what. Services alone cover every subscription.
          {options.groups.length ? '' : ' Subscription groups are made on the Breakdown tab.'}
        </p>
        <div className="azure-cost-analysis-picker">
          {options.groups.length ? (
            <PickList title="Subscription groups" currency={currency} chosen={focus.groups} onToggle={toggle('groups')}
                      rows={options.groups.map((group) => ({ name: group.name, note: group.match.join(', ') }))} />
          ) : null}
          <PickList title="Subscriptions" currency={currency} chosen={focus.subscriptions} onToggle={toggle('subscriptions')}
                    rows={options.subscriptions.map((row) => ({ name: row.name, monthly: row.monthly, note: row.group }))}
                    render={(name) => <SubscriptionLabel name={name} />} />
          <PickList title="Services" currency={currency} chosen={focus.services} onToggle={toggle('services')}
                    rows={options.services} />
        </div>
      </section>

      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!chosenCount(focus) ? <p className="empty-state">Choose services, subscriptions or a subscription group to analyse.</p>
        : loading && !report ? <Loading />
          : report && figures ? (
            <>
              <h2 className="azure-cost-analysis-title">{report.title}</h2>
              <div className="azure-cost-kpis">
                <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Monthly, last 3 closed months</span>
                  <strong>{formatMoney(figures.monthly_recent, currency)}</strong></div>
                <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Against the 3 before</span>
                  <strong><Pct value={figures.change_pct} /></strong></div>
                <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Share of the bill</span>
                  <strong>{figures.share_of_bill_pct == null ? '—' : `${figures.share_of_bill_pct}%`}</strong></div>
              </div>
              <CompassReading report={report} writing={writing} onWrite={write} />
              <section className="card azure-cost-card azure-cost-wide">
                <h3>By month</h3>
                <SeriesChart label={`${report.title} by month`} currency={currency} height={260}
                             categories={figures.months} categoryLabel={(month) => formatMonth(month, true)}
                             series={figures.services.slice(0, 6).map((row, index): Series => ({
                               name: row.name, stack: 'focus', color: index,
                               data: figures.months.map((month) => row.by_month[month] ?? 0),
                             })).concat(figures.services.length > 6 ? [{
                               name: 'Other', stack: 'focus', color: 'other',
                               data: figures.months.map((month) => figures.services.slice(6).reduce((sum, row) => sum + (row.by_month[month] ?? 0), 0)),
                             }] : [])} />
                {figures.current_month ? <p className="text-muted azure-cost-note">{formatMonth(figures.current_month)} is still being billed.</p> : null}
              </section>
              <div className="azure-cost-columns">
                <section className="card azure-cost-card"><h3>Services</h3><Rows rows={figures.services} kind="service" currency={currency} /></section>
                <section className="card azure-cost-card"><h3>Subscriptions</h3><Rows rows={figures.subscriptions} kind="subscription" currency={currency} /></section>
              </div>
              <details className="card azure-cost-card azure-cost-fold">
                <summary><h3>What Compass reads besides the figures</h3></summary>
                <div className="azure-cost-columns">
                  <div>
                    <h4>Meters, monthly over the footprint period</h4>
                    {report.built_from.meters.length ? (
                      <ul>{report.built_from.meters.map((row) => <li key={row.name}>{row.name}: {formatMoney(row.monthly, currency, true)}</li>)}</ul>
                    ) : <p className="text-muted">No footprint synced for these subscriptions.</p>}
                    <h4>Resource groups</h4>
                    {report.built_from.resource_groups.length ? (
                      <ul>{report.built_from.resource_groups.map((row) => <li key={row.name}>{row.name}: {formatMoney(row.monthly, currency, true)}</li>)}</ul>
                    ) : <p className="text-muted">None.</p>}
                  </div>
                  <div>
                    <h4>Tags naming it <span className="text-muted">(whole tagged spend, every service)</span></h4>
                    {report.tags.length ? (
                      <ul>{report.tags.map((row) => <li key={`${row.tag}|${row.value}`}>{row.tag} = {row.value}: {formatMoney(row.monthly, currency, true)}</li>)}</ul>
                    ) : <p className="text-muted">No tag value names it.</p>}
                    <h4>Solutions these subscriptions look like</h4>
                    {report.solutions.length ? (
                      <ul>{report.solutions.map((row) => <li key={row.subscription}><SubscriptionLabel name={row.subscription} />: {row.looks_like.join(', ')}</li>)}</ul>
                    ) : <p className="text-muted">None recognised.</p>}
                    <p className="text-muted">Industry: {report.industry ?? 'not set'}</p>
                  </div>
                </div>
              </details>
            </>
          ) : null}
    </>
  );
}
