import { Fragment, useEffect, useState } from 'react';
import {
  askPlacements, fetchPlacements, fetchProposalNote, type Placements, type ProposedSolution,
} from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney } from './format';
import { Loading } from './Loading';
import { Popup, PopupRow } from './Popup';
import { SubscriptionLabel } from './SubscriptionLabel';

const ASK_AT_ONCE = 24;
const money = (value: number) => formatMoney(value, 'USD', true);

function ProposalNote({ proposal, onClose }: { proposal: ProposedSolution; onClose: () => void }) {
  const [note, setNote] = useState<{ file: string; markdown: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { fetchProposalNote(proposal.name).then(setNote, (failure) => setError(errorText(failure))); }, [proposal.name]);
  return (
    <Popup kicker="Proposed solution" title={proposal.name} onClose={onClose} tall>
      {error ? <div className="azure-cost-error">{error}</div> : !note ? <Loading /> : (
        <>
          <p className="azure-cost-note">
            Paste this into a new note at <code>{note.file}</code> in the vault. From then on the rules place these
            subscriptions themselves, and the guide lists it; fill in its architecture, sizing and pitches like the others.
            {proposal.valid ? '' : ` Its rules need fixing first: ${proposal.problem}.`}
          </p>
          <div className="azure-cost-toolbar">
            <button type="button" className="btn btn-primary" onClick={() => {
              try { void navigator.clipboard.writeText(note.markdown).then(() => setCopied(true)); } catch { /* shown below */ }
            }}>{copied ? 'Copied' : 'Copy the note'}</button>
          </div>
          <pre className="azure-cost-note-source">{note.markdown}</pre>
        </>
      )}
    </Popup>
  );
}

/** The subscriptions the rules could not place, as Compass reads them (operator,
 *  2026-10-23: the second part of LLM enablement) -- one customer's, or everyone's. */
export function PlacementsCard({ customerId }: { customerId?: string }) {
  const [found, setFound] = useState<Placements | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ProposedSolution | null>(null);

  useEffect(() => { fetchPlacements(customerId).then(setFound, (failure) => setError(errorText(failure))); }, [customerId]);

  const ask = () => {
    setAsking(true); setError(null);
    askPlacements(customerId, ASK_AT_ONCE).then(setFound, (failure) => setError(errorText(failure)))
      .finally(() => setAsking(false));
  };
  const customerOf = (key: string) => key.slice(0, key.indexOf('|'));
  const subscriptionOf = (key: string) => key.slice(key.indexOf('|') + 1);

  if (!found) return error ? <div className="azure-cost-error">{error}</div> : null;
  const placed = Object.entries(found.suggestions);
  return (
    <section className="card azure-cost-card">
      <h3>Placed by Compass</h3>
      <p className="text-muted azure-cost-note">
        {found.unplaced} subscription{found.unplaced === 1 ? '' : 's'} the rules could not place; Compass has read{' '}
        {placed.length}. It names the solution each most likely is, from its services, meters and names -- a suggestion,
        not the rules' verdict. Where it proposes a new solution, add it to the vault and the rules take over.
      </p>
      {found.pending.length ? (
        <div className="azure-cost-toolbar">
          <button type="button" className="btn btn-primary" disabled={asking || !found.available} onClick={ask}>
            Ask Compass about the {Math.min(found.pending.length, ASK_AT_ONCE)} largest
          </button>
          {!found.available ? <span className="text-muted">Compass is not available to plugins on this install.</span> : null}
        </div>
      ) : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {asking ? <Loading label={`Compass is reading ${Math.min(found.pending.length, ASK_AT_ONCE)} subscriptions…`} /> : null}
      {placed.length ? (
        <table className="azure-cost-table">
          <thead><tr><th>Subscription</th>{customerId ? null : <th>Customer</th>}<th>Monthly</th><th>Compass says</th><th>Confidence</th></tr></thead>
          <tbody>
            {placed.map(([key, item]) => (
              <Fragment key={key}>
                <tr className="azure-cost-clickable" onClick={() => setOpen(key)}>
                  <td><DrillLink kind="subscription" name={subscriptionOf(key)} customerId={customerId ? undefined : customerOf(key)} /></td>
                  {customerId ? null : <td>{item.customer}</td>}
                  <td>{money(item.monthly)}</td>
                  <td>{item.solution ?? (item.proposal ? <>New: <strong>{item.proposal.name}</strong></> : <span className="text-muted">Cannot tell</span>)}</td>
                  <td>{item.confidence}</td>
                </tr>
                {open === key ? (
                  <PopupRow kicker="Compass's placement" title={subscriptionOf(key)}
                            label={<SubscriptionLabel name={subscriptionOf(key)} />} onClose={() => setOpen(null)}>
                    <p><strong>{item.solution ?? item.proposal?.name ?? 'Not placed'}</strong> · {item.confidence} confidence</p>
                    <p>{item.reason}</p>
                  </PopupRow>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : null}
      {found.proposals.length ? (
        <>
          <h4>New solutions Compass proposes</h4>
          <table className="azure-cost-table">
            <thead><tr><th>Solution</th><th>Solution play</th><th>Subscriptions</th><th>Customers</th><th>Monthly</th><th /></tr></thead>
            <tbody>
              {found.proposals.map((item) => (
                <tr key={item.name}>
                  <td><strong>{item.name}</strong><br /><span className="text-muted">{item.description}</span></td>
                  <td>{item.play ?? '—'}</td><td>{item.subscriptions.length}</td>
                  <td className="text-muted">{item.customers.join(', ')}</td><td>{money(item.monthly)}</td>
                  <td><button type="button" className="btn" onClick={() => setProposal(item)}>Get the Solution note</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : null}
      {proposal ? <ProposalNote proposal={proposal} onClose={() => setProposal(null)} /> : null}
    </section>
  );
}
