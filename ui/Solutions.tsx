import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { NoteText } from '../../pluginHost/noteText';
import {
  fetchCustomerSolutions, fetchSolutionCatalog, fetchSolutionsAcross, reportExportPath,
  startTagSync, type CustomerSolutions, type SolutionCatalog, type SolutionGuide, type SolutionsAcross,
  type SubscriptionSolutions,
} from './client';
import { DrillLink } from './Drill';
import { PlacementsCard } from './Placements';
import { PopupRow } from './Popup';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink } from './ReportsHome';
import { Loading } from './Loading';
import { DraftButton, SizeIt } from './Advisor';

const ALL_PLAYS = 'All plays';
// The footprint is Cost Management's actual cost, billed in USD for these agreements.
const money = (value: number) => formatMoney(value, 'USD', true);

function windowText(window: { first_month: string | null; last_month: string | null } | null): string {
  return window?.first_month && window.last_month
    ? `${formatMonth(window.first_month)} – ${formatMonth(window.last_month)}` : 'not synced yet';
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card azure-cost-kpi">
      <span className="azure-cost-kpi-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PlayChips({ plays, chosen, onChoose }: { plays: string[]; chosen: string; onChoose: (play: string) => void }) {
  return (
    <div className="azure-cost-chips" role="group" aria-label="Solution play">
      {[ALL_PLAYS, ...plays].map((play) => (
        <button key={play} type="button" className={chosen === play ? 'active' : undefined}
                aria-pressed={chosen === play} onClick={() => onChoose(play)}>{play}</button>
      ))}
    </div>
  );
}

/** A solution's guide from its vault note: the sizing bill and the architecture diagram. */
export function SolutionDetail({ guide, customerId }: { guide: SolutionGuide; customerId?: string }) {
  if (!guide.note) return <p className="text-muted">No Solution note in the vault for this one yet.</p>;
  return (
    <div>
      <p><Link to={`/browse/${encodeURIComponent(guide.note)}`}>Read the solution guide: {guide.note}</Link></p>
      {guide.sizing ? (
        <table className="azure-cost-table">
          <thead><tr><th>Building block</th><th>Service</th><th>Small</th><th>Medium</th><th>Large</th><th>Basis</th></tr></thead>
          <tbody>
            {guide.sizing.rows.map((row) => (
              <tr key={row.block}>
                <td>{row.block}</td><td>{row.service}</td>
                <td>{row.small != null ? money(row.small) : '—'}</td><td>{row.medium != null ? money(row.medium) : '—'}</td>
                <td>{row.large != null ? money(row.large) : '—'}</td><td className="text-muted">{row.basis}</td>
              </tr>
            ))}
            <tr><td><strong>Monthly, list price</strong></td><td />
              <td><strong>{money(guide.sizing.totals.small)}</strong></td><td><strong>{money(guide.sizing.totals.medium)}</strong></td>
              <td><strong>{money(guide.sizing.totals.large)}</strong></td><td /></tr>
          </tbody>
        </table>
      ) : <p className="text-muted">The note has no sizing table yet.</p>}
      {guide.architecture ? <NoteText text={guide.architecture} /> : null}
      {guide.id && guide.sizing ? <SizeIt solutionId={guide.id} customerId={customerId} /> : null}
    </div>
  );
}

function SubscriptionRow({ row }: { row: SubscriptionSolutions }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="azure-cost-clickable" onClick={() => setOpen(!open)}>
        <td><DrillLink kind="subscription" name={row.subscription} /></td>
        <td>{money(row.monthly)}</td>
        <td>{row.environment ?? '—'}</td>
        <td>
          {row.solutions.length ? row.solutions.map((found) => (
            <span key={found.id} className="azure-cost-tag-key" title={found.play}>
              {found.name}{found.confidence === 'likely' ? ' (likely)' : ''}
            </span>
          )) : <span className="text-muted">Not placed</span>}
          {row.also.length ? <span className="text-muted"> · also {row.also.map((found) => found.name).join(', ')}</span> : null}
        </td>
        <td className="text-muted">{row.top_services.slice(0, 3).map((service, index) => (
          <span key={service.name}>{index ? ', ' : ''}<DrillLink kind="service" name={service.name} /></span>))}</td>
      </tr>
      {open ? (
        <PopupRow kicker="Subscription" title={row.subscription} onClose={() => setOpen(false)}>
            {[...row.solutions, ...row.also].map((found) => (
              <p key={found.id}>
                <strong>{found.name}</strong> ({found.play}, {found.confidence}):{' '}
                {found.evidence.map((item) => item.monthly != null ? `${item.name} ${money(item.monthly)}/mo` : item.name).join(' · ')}
                {found.named.length ? ` · named ${found.named.map((word) => `'${word}'`).join(', ')}` : ''}
              </p>
            ))}
            <p className="text-muted">
              Largest services: {row.top_services.map((service) => `${service.name} ${money(service.monthly)}`).join(' · ')}
              {row.resource_groups.length ? <><br />Resource groups: {row.resource_groups.join(', ')}</> : null}
            </p>
          </PopupRow>
      ) : null}
    </>
  );
}

/** One customer's subscriptions, the solution each looks like, and what to pitch
 *  (operator, 2026-10-23: for the Solution Sellers). */
export function SolutionsTab({ customerId, syncedVersion }: { customerId: string; syncedVersion: number }) {
  const [view, setView] = useState<CustomerSolutions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [play, setPlay] = useState(ALL_PLAYS);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchCustomerSolutions(customerId).then((found) => { setView(found); setError(null); },
      (failure) => setError(errorText(failure)));
  }, [customerId, syncedVersion]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!view) return <Loading />;

  const sync = (
    <button type="button" className="btn" onClick={() => startTagSync(customerId).then(
      (status) => setNotice(status.started ? 'Sync started; the page fills in when it finishes.' : 'A sync is already running.'),
      (failure) => setNotice(errorText(failure)))}>Sync tags and solutions</button>
  );
  if (!view.synced) {
    return (
      <>
        <p className="empty-state">What this customer's subscriptions are used for is not synced yet. It is read with the tags.</p>
        <div className="azure-cost-toolbar">{sync}</div>
        {notice ? <p className="text-muted azure-cost-note">{notice}</p> : null}
      </>
    );
  }
  const plays = [...new Set(view.solutions.map((item) => item.play))];
  const rows = view.subscriptions.filter((row) => play === ALL_PLAYS || row.solutions.some((found) => found.play === play));
  const pitches = view.pitches.filter((pitch) => play === ALL_PLAYS || pitch.play === play);
  return (
    <>
      <p className="text-muted azure-cost-note">
        Monthly averages over {windowText(view.window)}. Each subscription is placed by the services it runs, its meters
        and the words in its and its resource groups' names. <em>Likely</em>: the required services only; otherwise
        supporting services or a telling name agree. A solution under 2% of a subscription's spend, without a name
        saying so, is listed as <em>also</em> and does not drive pitches. A pitch is the piece a solution usually has that this customer runs
        nowhere. Click a subscription for the evidence.
      </p>
      <div className="azure-cost-kpis">
        <Kpi label="Subscriptions" value={view.subscriptions.length} />
        <Kpi label="Solutions found" value={view.solutions.length} />
        <Kpi label="Pitches" value={view.pitches.length} />
        <Kpi label="Not placed" value={`${view.unclassified.count} · ${money(view.unclassified.monthly)}/mo`} />
      </div>
      <PlayChips plays={plays} chosen={play} onChoose={setPlay} />
      <section className="card azure-cost-card">
        <h3>Solutions</h3>
        <table className="azure-cost-table">
          <thead><tr><th>Solution</th><th>Solution play</th><th>Subscriptions</th><th>Monthly in them</th><th>Sized, small – large</th></tr></thead>
          <tbody>
            {view.solutions.filter((item) => play === ALL_PLAYS || item.play === play).map((item) => (
              <Fragment key={item.id}>
                <tr className="azure-cost-clickable" onClick={() => setOpen(open === item.id ? null : item.id)}>
                  <td>{open === item.id ? '▾' : '▸'} {item.name}</td><td>{item.play}</td><td>{item.subscriptions}</td>
                  <td>{money(item.monthly)}</td>
                  <td>{item.sizing ? `${money(item.sizing.totals.small)} – ${money(item.sizing.totals.large)}` : '—'}</td></tr>
                {open === item.id ? (
                  <PopupRow kicker="Solution" title={item.name} onClose={() => setOpen(null)}><SolutionDetail guide={item} customerId={view.customer.id} /></PopupRow>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card azure-cost-card">
        <h3>What to pitch</h3>
        {pitches.length ? (
          <table className="azure-cost-table">
            <thead><tr><th>Pitch</th><th>Because of</th><th>Subscriptions</th><th /></tr></thead>
            <tbody>
              {pitches.map((pitch) => (
                <tr key={`${pitch.solution}|${pitch.pitch}`}><td>{pitch.pitch}</td><td>{pitch.solution}</td>
                  <td className="text-muted">{pitch.subscriptions.join(', ')}</td>
                  <td><DraftButton customerId={view.customer.id} pitch={pitch.pitch} /></td></tr>
              ))}
            </tbody>
          </table>
        ) : <p className="text-muted">Nothing obvious missing.</p>}
      </section>
      <section className="card azure-cost-card">
        <h3>Subscriptions</h3>
        <table className="azure-cost-table">
          <thead><tr><th>Subscription</th><th>Monthly</th><th>Environment</th><th>Looks like</th><th>Largest services</th></tr></thead>
          <tbody>{rows.map((row) => <SubscriptionRow key={row.subscription} row={row} />)}</tbody>
        </table>
      </section>
      {view.unclassified.count ? <PlacementsCard customerId={view.customer.id} /> : null}
      <div className="azure-cost-toolbar">{sync}</div>
      {notice ? <p className="text-muted azure-cost-note">{notice}</p> : null}
    </>
  );
}

/** Who runs which solution across every customer, every pitch, and the largest
 *  subscriptions no pattern places. */
export function SolutionsPage() {
  const [report, setReport] = useState<SolutionsAcross | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [play, setPlay] = useState(ALL_PLAYS);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchSolutionsAcross().then(setReport, (failure) => setError(errorText(failure)));
  }, []);

  const plays = useMemo(() => [...new Set((report?.by_solution ?? []).map((item) => item.play))], [report]);
  const solutions = (report?.by_solution ?? []).filter((item) => play === ALL_PLAYS || item.play === play);
  const pitches = (report?.pitches ?? []).filter((pitch) => play === ALL_PLAYS || pitch.play === play);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Solutions' }]} />
      <header className="azure-cost-header">
        <h1>Solutions</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('solutions'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        What each customer's subscriptions look like they are used for, over {windowText(report?.window ?? null)}, and
        what to pitch: the piece a solution usually has that the customer runs nowhere. Read from each subscription's
        services, meters and names with the patterns in Settings. Groups include their affiliates; a subscription can
        run more than one solution, so the monthly figures overlap.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!report ? <Loading /> : !report.window ? (
        <p className="empty-state">Nothing synced yet. Sync tags (Settings &gt; Sync) to read what each subscription is used for.</p>
      ) : (
        <>
          <div className="azure-cost-kpis">
            <Kpi label="Customers" value={report.customers.length} />
            <Kpi label="Subscriptions" value={report.subscriptions.length} />
            <Kpi label="Pitches" value={report.pitches.length} />
            <Kpi label="Not placed" value={report.unclassified.length} />
          </div>
          <PlayChips plays={plays} chosen={play} onChoose={setPlay} />
          <section className="card azure-cost-card">
            <h3>By solution</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Solution</th><th>Solution play</th><th>Customers</th>
                <th>Subscriptions</th><th>Monthly in them</th></tr></thead>
              <tbody>
                {solutions.map((item) => (
                  <Fragment key={item.id}>
                    <tr className="azure-cost-clickable" onClick={() => setOpen(open === item.id ? null : item.id)}>
                      <td>{item.name}</td><td>{item.play}</td><td>{item.customers.length}</td>
                      <td>{item.subscriptions}</td><td>{money(item.monthly)}</td>
                    </tr>
                    {open === item.id ? (
                      <PopupRow kicker="Solution" title={item.name} onClose={() => setOpen(null)}>
                        <p className="text-muted">{item.customers.join(', ')}</p>
                        <SolutionDetail guide={item} />
                      </PopupRow>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card azure-cost-card">
            <h3>What to pitch</h3>
            <table className="azure-cost-table">
              <thead><tr><th>Customer</th><th>Pitch</th><th>Because of</th></tr></thead>
              <tbody>
                {pitches.map((pitch) => (
                  <tr key={`${pitch.customer_id}|${pitch.solution}|${pitch.pitch}`}>
                    <td><Link to={reportLink('Solutions', pitch.customer_id)}>{pitch.customer}</Link></td>
                    <td>{pitch.pitch}</td><td className="text-muted">{pitch.solution}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {play === ALL_PLAYS ? (
            <section className="card azure-cost-card">
              <h3>Not placed, the largest first</h3>
              <p className="text-muted azure-cost-note">Subscriptions no pattern fits: candidates for a new pattern, or for Compass to read.</p>
              <table className="azure-cost-table">
                <thead><tr><th>Customer</th><th>Subscription</th><th>Monthly</th><th>Largest services</th></tr></thead>
                <tbody>
                  {report.unclassified.slice(0, 50).map((row) => (
                    <tr key={`${row.customer_id}|${row.subscription}`}>
                      <td><Link to={reportLink('Solutions', row.customer_id)}>{row.customer}</Link></td>
                      <td><DrillLink kind="subscription" name={row.subscription} customerId={row.customer_id} /></td>
                      <td>{money(row.monthly)}</td>
                      <td className="text-muted">{row.top_services.map((service, index) => (
                        <span key={service.name}>{index ? ', ' : ''}
                          <DrillLink kind="service" name={service.name} customerId={row.customer_id} /></span>))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
          {play === ALL_PLAYS && report.unclassified.length ? <PlacementsCard /> : null}
        </>
      )}
    </div>
  );
}

/** Where the patterns come from: the vault's Solution notes, each one a guide the
 *  seller reads and the rules this report matches with. */
export function SolutionCatalogCard() {
  const [catalog, setCatalog] = useState<SolutionCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetchSolutionCatalog().then(setCatalog, (failure) => setError(errorText(failure))); }, []);

  return (
    <section className="card azure-cost-card">
      <h3>Solution patterns</h3>
      <p className="text-muted azure-cost-note">
        Each solution is a <strong>Solution</strong> note in the vault (Work/Solutions): a guide for the seller -- what it
        is, its architecture, how it shows in the bill, what to pitch and a sizing bill -- whose <code>## Pattern</code>
        section holds the rules this report matches subscriptions with. Edit a note in Obsidian and the report follows
        within a minute. A note whose Pattern does not read is left out and named below.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!catalog ? <Loading /> : (
        <>
          <p className="azure-cost-note">
            {catalog.source === 'vault'
              ? `${catalog.patterns.length} patterns from the vault's Solution notes.`
              : 'No Solution note in the vault yet: the patterns shipped with the plugin apply.'}
          </p>
          {catalog.notes.length ? (
            <table className="azure-cost-table">
              <thead><tr><th>Solution note</th><th>Id</th><th>Status</th><th>Problem</th></tr></thead>
              <tbody>
                {catalog.notes.map((note) => (
                  <tr key={note.stem}>
                    <td><Link to={`/browse/${encodeURIComponent(note.stem)}`}>{note.name}</Link></td>
                    <td>{note.id ?? '—'}</td><td>{note.status ?? '—'}</td>
                    <td className={note.error ? 'azure-cost-warning' : undefined}>{note.error ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </>
      )}
    </section>
  );
}
