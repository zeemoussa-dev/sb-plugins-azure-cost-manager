import { Fragment, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { NoteText } from '../../pluginHost/noteText';
import {
  askData, classifyMarketplace, createOpportunity, draftFromPitch, fetchActions, fetchExplain, fetchMarketplaceClasses,
  sizeSolution, writeActions, writeExplain,
  type Answer, type DraftOpportunity, type DrillKind, type Explanation, type Kept, type MarketplaceClasses, type NextAction, type SizedSolution,
} from './client';
import { errorText, formatMoney } from './format';
import { Loading } from './Loading';
import { Popup, PopupRow } from './Popup';
import { reportLink } from './ReportsHome';

// The seller's Compass features (operator, 2026-10-23). Every figure shown is the
// plugin's -- Compass explains, ranks and drafts around them.
const money = (value: number | null | undefined) => (value == null ? '—' : formatMoney(value, 'USD', true));
const range = (sized: number[] | null | undefined) => (sized ? `${money(sized[0])} – ${money(sized[2])} a month` : null);

function copy(text: string, done: () => void) {
  try { void navigator.clipboard.writeText(text).then(done); } catch { /* the text is on screen */ }
}

/** What moved and why, for one drilled item -- written on asking, kept until its data moves. */
export function ExplainBox({ customerId, kind, name, accounts }: {
  customerId: string; kind: DrillKind; name: string; accounts: string[] | null;
}) {
  const [found, setFound] = useState<Explanation | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  useEffect(() => {
    setFound(null); setError(null); setReply('');
    fetchExplain(customerId, kind, name, accounts).then(setFound, (failure) => setError(errorText(failure)));
  }, [customerId, kind, name, accounts?.join(',')]);
  const write = (note?: string) => {
    setWriting(true); setError(null);
    writeExplain(customerId, kind, name, accounts, note).then((done) => { setFound(done); setReply(''); },
      (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  if (!found) return null;
  return (
    <div className="azure-cost-explain">
      {writing ? <Loading label="Compass is reading this item's months and what it is made of…" /> : found.value ? (
        <>
          <NoteText text={found.value} />
          {found.stale ? <p className="azure-cost-warning">Its data has changed since this was written.</p> : null}
          {found.notes.length ? (
            <div className="azure-cost-note">
              <span className="azure-cost-kpi-label">What you told Compass</span>
              <ul>{found.notes.map((note, index) => <li key={index}>{note.said} <span className="text-muted">({note.on})</span></li>)}</ul>
            </div>
          ) : null}
          <form className="azure-cost-explain-reply" onSubmit={(event) => { event.preventDefault(); if (reply.trim()) write(reply); }}>
            <label className="field-labeled">The customer's answer, or what you know
              <textarea rows={2} value={reply} onChange={(event) => setReply(event.target.value)}
                        placeholder="e.g. They are moving the SAP estate from on-premises this quarter" />
            </label>
            <button type="submit" className="btn btn-primary" disabled={!reply.trim() || !found.available}>Update the explanation</button>
          </form>
        </>
      ) : null}
      {!writing ? (
        <button type="button" className="btn" disabled={!found.available} onClick={() => write()}
                title={found.available ? 'Compass explains what moved, where and why, from the figures below' : 'Compass is not available to plugins on this install'}>
          {found.value ? 'Explain again' : 'Explain this'}</button>
      ) : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
    </div>
  );
}

const URGENCY_CLASS: Record<string, string> = { now: 'spike', 'this quarter': 'new', later: 'drop' };

/** The seller's next best actions across every customer, ranked by Compass. */
export function ActionsPage() {
  const [found, setFound] = useState<Kept<NextAction[]> | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { fetchActions().then(setFound, (failure) => setError(errorText(failure))); }, []);
  const write = () => {
    setWriting(true); setError(null);
    writeActions().then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Next best actions' }]} />
      <header className="azure-cost-header">
        <h1>Next best actions</h1>
        <button type="button" className="btn btn-primary" disabled={writing || !found?.available} onClick={write}>
          {found?.value ? 'Rank again' : 'Ask Compass'}</button>
      </header>
      <p className="text-muted azure-cost-note">
        Compass ranks what is most worth doing across your 30 largest customers -- MACCs running out or falling short,
        growth and decline, pitches with their sizing, thin pipeline, your quota. The sizing shown is the Solution
        note's, not Compass's. Open a customer for its brief.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!found || writing ? <Loading label={writing ? 'Compass is weighing every customer…' : 'Loading…'} /> : !found.value ? (
        <p className="empty-state">{found.available ? 'Ask Compass to rank your next best actions.' : 'Compass is not available to plugins on this install.'}</p>
      ) : (
        <section className="card azure-cost-card">
          {found.stale ? <p className="azure-cost-warning">The data has changed since this ranking. Rank again for the latest.</p> : null}
          <table className="azure-cost-table">
            <thead><tr><th>#</th><th>When</th><th>Customer</th><th>Action</th><th>Sized</th></tr></thead>
            <tbody>
              {found.value.map((item, index) => (
                <Fragment key={`${item.customer_id}|${index}`}>
                  <tr className="azure-cost-clickable" onClick={() => setOpen(index)}>
                    <td>{index + 1}</td>
                    <td><span className={`azure-cost-anomaly ${URGENCY_CLASS[item.urgency] ?? 'new'}`}>{item.urgency}</span></td>
                    <td><Link to={reportLink('Overview', item.customer_id)} onClick={(event) => event.stopPropagation()}>{item.customer}</Link></td>
                    <td>{item.action}</td>
                    <td className="text-muted">{range(item.sized_monthly) ?? '—'}</td>
                  </tr>
                  {open === index ? (
                    <PopupRow kicker={`Next best action · ${item.urgency}`} title={item.customer} onClose={() => setOpen(null)}>
                      <p><strong>{item.action}</strong></p>
                      <p>{item.why}</p>
                      {item.pitch ? <p>Pitch: {item.pitch}{item.sized_monthly ? ` (${range(item.sized_monthly)}, list price)` : ''}</p> : null}
                      <p className="text-muted">Last month: {money(item.last_month)}</p>
                      <p><Link to={reportLink('Solutions', item.customer_id)}>Open {item.customer}'s solutions and pitches</Link></p>
                    </PopupRow>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          {found.at ? <p className="text-muted azure-cost-note">Ranked {new Date(found.at).toLocaleString()} by Compass.</p> : null}
        </section>
      )}
    </div>
  );
}

/** An opportunity and an email drafted from a pitch, edited, then created. */
export function DraftButton({ customerId, pitch }: { customerId: string; pitch: string }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftOpportunity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<'idle' | 'creating' | 'created'>('idle');
  const [copied, setCopied] = useState(false);
  const start = () => {
    setOpen(true); setDraft(null); setError(null); setState('idle');
    draftFromPitch(customerId, pitch).then(setDraft, (failure) => setError(errorText(failure)));
  };
  const create = () => {
    if (!draft) return;
    setState('creating');
    createOpportunity(customerId, '', draft.title.trim(),
      { status: 'Open', stage: 'Identified', ...(draft.expected_monthly != null ? { expected_monthly_usd: draft.expected_monthly } : {}) }, [])
      .then(() => setState('created'), (failure) => { setState('idle'); setError(errorText(failure)); });
  };
  return (
    <>
      <button type="button" className="btn" onClick={start}>Draft</button>
      {open ? (
        <Popup kicker="Draft from a pitch" title={pitch} onClose={() => setOpen(false)} tall>
          {error && !draft ? <div className="azure-cost-error">{error}</div> : !draft ? (
            <Loading label="Compass is drafting the opportunity and an email…" />
          ) : (
            <div className="azure-cost-editor">
              <h4>Opportunity</h4>
              <label className="field-labeled">Title
                <input type="text" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
              </label>
              <p className="azure-cost-note">{draft.summary}</p>
              <p className="azure-cost-note">
                Expected: <strong>{money(draft.expected_monthly)}</strong> a month -- the {draft.size} size of the
                {' '}{draft.solution} note's sizing, at list price.
              </p>
              {draft.next_steps.length ? <ul>{draft.next_steps.map((step) => <li key={step}>{step}</li>)}</ul> : null}
              <div className="azure-cost-toolbar">
                <button type="button" className="btn btn-primary" disabled={state !== 'idle' || !draft.title.trim()} onClick={create}>
                  {state === 'creating' ? 'Creating…' : state === 'created' ? 'Created' : 'Create opportunity'}</button>
                {state === 'created' ? <span className="text-muted">Added to the customer's pipeline as Identified.</span> : null}
              </div>
              <h4>Email to the customer</h4>
              <label className="field-labeled">Subject
                <input type="text" value={draft.email_subject} onChange={(event) => setDraft({ ...draft, email_subject: event.target.value })} />
              </label>
              <label className="field-labeled">Body
                <textarea rows={9} value={draft.email_body} onChange={(event) => setDraft({ ...draft, email_body: event.target.value })} />
              </label>
              <div className="azure-cost-toolbar">
                <button type="button" className="btn" onClick={() => copy(`Subject: ${draft.email_subject}\n\n${draft.email_body}`, () => setCopied(true))}>
                  {copied ? 'Copied' : 'Copy the email'}</button>
              </div>
              {error ? <div className="azure-cost-error">{error}</div> : null}
            </div>
          )}
        </Popup>
      ) : null}
    </>
  );
}

/** Sizing a solution for one customer from its template bill: Compass picks a size and a
 *  factor per block from what the seller knows; the money is the bill's. */
export function SizeIt({ solutionId, customerId }: { solutionId: string; customerId?: string }) {
  const [answers, setAnswers] = useState('');
  const [sized, setSized] = useState<SizedSolution | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = () => {
    setBusy(true); setError(null);
    sizeSolution(solutionId, answers, customerId).then(setSized, (failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  return (
    <div className="azure-cost-editor">
      <h4>Size it for a customer</h4>
      <label className="field-labeled">What you know -- users, data, requests, environments, regions
        <textarea rows={3} value={answers} placeholder="e.g. 2,000 internal users, 50,000 documents, prod and dev, UAE North only"
                  onChange={(event) => setAnswers(event.target.value)} />
      </label>
      <div className="azure-cost-toolbar">
        <button type="button" className="btn btn-primary" disabled={busy || !answers.trim()} onClick={run}>Size it</button>
      </div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {busy ? <Loading label="Compass is sizing each building block…" /> : sized ? (
        <>
          <table className="azure-cost-table">
            <thead><tr><th>Building block</th><th>Size</th><th>× factor</th><th>Monthly</th><th>Why</th></tr></thead>
            <tbody>
              {sized.rows.map((row) => (
                <tr key={row.block}><td>{row.block}<br /><span className="text-muted">{row.service}</span></td>
                  <td>{row.size}</td><td>{row.factor}</td><td>{money(row.monthly)}</td>
                  <td className="text-muted">{row.reason}</td></tr>
              ))}
              <tr><td><strong>Monthly, list price</strong></td><td /><td /><td><strong>{money(sized.total)}</strong></td><td /></tr>
            </tbody>
          </table>
          {sized.assumptions.length ? <p className="azure-cost-note">Assumed: {sized.assumptions.join('; ')}</p> : null}
          {sized.questions.length ? <p className="azure-cost-note">To firm it up, ask: {sized.questions.join('; ')}</p> : null}
          <p className="text-muted azure-cost-note">The money is the note's list-price bill times the factor; confirm in the Azure pricing calculator.</p>
        </>
      ) : null}
    </div>
  );
}

/** A question about the customers, answered from the reports Compass chose to read. */
export function AskBox() {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = () => {
    setBusy(true); setError(null); setAnswer(null);
    askData(question).then(setAnswer, (failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  return (
    <section className="card azure-cost-card">
      <form className="azure-cost-toolbar azure-cost-ask" onSubmit={(event) => { event.preventDefault(); if (question.trim()) run(); }}>
        <input type="search" value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Ask about your customers"
               placeholder="Ask about your customers -- e.g. who runs Databricks but not Purview? Whose MACC runs out this year?" />
        <button type="submit" className="btn btn-primary" disabled={busy || !question.trim()}>Ask</button>
      </form>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {busy ? <Loading label="Compass is reading the reports…" /> : answer ? (
        <>
          <NoteText text={answer.answer} />
          {answer.calls.length ? (
            <p className="text-muted azure-cost-note">Read from: {answer.calls.map((call) =>
              `${call.report}${Object.keys(call.args).length ? ` (${Object.values(call.args).join(', ')})` : ''}`).join(' · ')}</p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

/** What each Marketplace product is, in Compass's words, for the SaaS popup. */
export function useMarketplaceClasses(active: boolean): [MarketplaceClasses | null, () => void, boolean, string | null] {
  const [found, setFound] = useState<MarketplaceClasses | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (active) fetchMarketplaceClasses().then(setFound, (failure) => setError(errorText(failure)));
  }, [active]);
  const classify = () => {
    setBusy(true); setError(null);
    classifyMarketplace().then(setFound, (failure) => setError(errorText(failure))).finally(() => setBusy(false));
  };
  return [found, classify, busy, error];
}
