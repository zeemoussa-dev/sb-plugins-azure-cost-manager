import { useEffect, useState } from 'react';
import { NoteText } from '../../pluginHost/noteText';
import {
  fetchSavingsPlan, fetchSavingsReport, OPTION_LABELS, writeSavingsPlan, writeSavingsReport,
  type Kept, type SavingsMove, type SavingsPlan,
} from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney } from './format';
import { Loading } from './Loading';
import { Popup } from './Popup';

const MOVE_LABELS: Record<SavingsMove['kind'], string> = {
  reserve: 'Reserve',
  savings_plan: 'Savings plan',
  hybrid_benefit: 'Azure Hybrid Benefit',
  keep_on_demand: 'Keep on demand',
  investigate: 'Ask about',
};

const PLAN_FOLDED_KEY = 'azure-cost-manager.savings-plan-folded';

function readFolded(): boolean {
  try { return localStorage.getItem(PLAN_FOLDED_KEY) === '1'; } catch { return false; }
}

function MoveSubject({ move }: { move: SavingsMove }) {
  return move.subject === 'subscription' ? <DrillLink kind="subscription" name={move.ref} /> : <>{move.ref}</>;
}

/** Compass's savings plan over the FinOps findings (operator, 2026-10-24): what to commit,
 *  what to leave on demand and why, the risk of each, and the savings told as money to
 *  reinvest. Every saving shown is the plugin's estimate, never the model's. */
export function SavingsPlanCard({ customerId, currency, accounts }: {
  customerId: string; currency: string | null; accounts?: string[];
}) {
  const [found, setFound] = useState<Kept<SavingsPlan> | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Folded or not is the viewer's choice, kept across customers and visits.
  const [open, setOpen] = useState(() => !readFolded());
  const fold = (nowOpen: boolean) => {
    setOpen(nowOpen);
    try { localStorage.setItem(PLAN_FOLDED_KEY, nowOpen ? '0' : '1'); } catch { /* storage may be blocked */ }
  };
  useEffect(() => {
    setFound(null);
    fetchSavingsPlan(customerId, accounts).then(setFound, (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, accounts?.join(',')]);
  const write = () => {
    setWriting(true); setError(null);
    writeSavingsPlan(customerId, accounts).then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  if (!found) return error ? <div className="azure-cost-error">{error}</div> : null;
  const plan = found.value;
  return (
    <details className="card azure-cost-card azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head">
        <h3>Savings plan</h3>
        {plan && !open ? <span className="text-muted">{plan.moves.length} move{plan.moves.length === 1 ? '' : 's'}{found.stale ? ' · out of date' : ''}</span> : null}
        {/* preventDefault: a click on the button must not fold the card. */}
        <button type="button" className="btn btn-primary" disabled={writing || !found.available}
                onClick={(event) => { event.preventDefault(); fold(true); write(); }}
                title={found.available ? 'Compass weighs the candidates, coverage, renewals, licenses, growth, the MACC, pitches and what you told it'
                  : 'Compass is not available to plugins on this install'}>
          {plan ? 'Ask again' : 'Ask Compass for a savings plan'}</button>
      </summary>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {writing ? <Loading label="Compass is weighing what to commit, what to hold and what to reinvest…" /> : plan ? (
        <>
          {found.stale ? <p className="azure-cost-warning">The findings have changed since. Ask again for the latest.</p> : null}
          <p>{plan.summary}</p>
          {plan.moves.length ? (
            <table className="azure-cost-table">
              <thead><tr><th>Move</th><th>On</th><th>Monthly now</th><th>Saves / month</th><th>Risk</th><th>Why</th></tr></thead>
              <tbody>
                {plan.moves.map((move) => (
                  <tr key={`${move.kind}|${move.ref}`}>
                    <td>{MOVE_LABELS[move.kind]}{move.option ? <><br /><span className="text-muted">{OPTION_LABELS[move.option]}</span></> : null}</td>
                    <td><MoveSubject move={move} /></td>
                    <td>{move.monthly != null ? formatMoney(move.monthly, currency) : '—'}</td>
                    <td>{move.saving_monthly != null
                      ? `${move.kind === 'hybrid_benefit' ? 'up to ' : ''}${formatMoney(move.saving_monthly, currency)}` : '—'}</td>
                    <td>{move.risk}{move.risk_reason ? <><br /><span className="text-muted">{move.risk_reason}</span></> : null}</td>
                    <td>{move.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {plan.reinvest ? <><h4>Reinvest the savings</h4><p>{plan.reinvest}</p></> : null}
          {plan.questions.length ? (
            <><h4>Ask the customer</h4><ul>{plan.questions.map((question) => <li key={question}>{question}</li>)}</ul></>
          ) : null}
          <p className="text-muted azure-cost-note">
            Compass's plan. Savings are the plugin's estimates from Azure's public prices; Hybrid Benefit only where the
            customer holds the licenses.
          </p>
        </>
      ) : <p className="text-muted">Compass turns the findings below into what to commit, what to hold and how to reinvest the savings.</p>}
    </details>
  );
}

function SavingsReportBody({ customerId, accounts }: { customerId: string; accounts?: string[] }) {
  const [found, setFound] = useState<Kept<string> | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const write = () => {
    setWriting(true); setError(null);
    writeSavingsReport(customerId, accounts).then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  useEffect(() => {
    fetchSavingsReport(customerId, accounts).then((kept) => {
      setFound(kept);
      if (!kept.kept && kept.available) write();
    }, (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, accounts?.join(',')]);

  if (error && !found?.value) return <div className="azure-cost-error">{error}</div>;
  if (!found || writing) return <Loading label={writing ? 'Compass is writing the savings report — this can take a minute…' : 'Loading…'} />;
  if (!found.value) {
    return <p className="empty-state">{found.available ? 'No report yet.' : 'Compass is not available to plugins on this install.'}</p>;
  }
  const copy = () => {
    try {
      void navigator.clipboard.writeText(found.value ?? '').then(() => setCopied(true));
    } catch { /* the clipboard may be blocked; the text is on screen */ }
  };
  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">
          Written by Compass from this customer's own findings only — nothing about pitches, quota or pipeline. Check before you send it.
        </span>
        <button type="button" className="btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <button type="button" className="btn" disabled={writing || !found.available} onClick={write}>Write again</button>
      </div>
      {found.stale ? <p className="azure-cost-warning">The findings have changed since. Write it again for the latest.</p> : null}
      <div className="azure-cost-brief"><NoteText text={found.value} /></div>
    </>
  );
}

/** A savings report to hand the customer (operator, 2026-10-24). */
export function SavingsReportButton({ customerId, customerName, accounts }: {
  customerId: string; customerName: string; accounts?: string[];
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)}
              title="A savings report for the customer's IT and finance leads, written by Compass">Savings report</button>
      {open ? (
        <Popup kicker="Savings report for the customer" title={customerName} onClose={() => setOpen(false)} tall>
          <SavingsReportBody customerId={customerId} accounts={accounts} />
        </Popup>
      ) : null}
    </>
  );
}
