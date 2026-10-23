import { useEffect, useState } from 'react';
import { NoteText } from '../../pluginHost/noteText';
import { fetchBrief, fetchMemory, forget, remember, writeBrief, type CustomerBrief, type MemoryLine } from './client';
import { errorText } from './format';
import { Loading } from './Loading';
import { Popup } from './Popup';

/** The brief before a meeting (operator, 2026-10-23): written by Compass over the
 *  figures the reports computed, kept until the data moves, written again on asking. */
function BriefBody({ customerId }: { customerId: string }) {
  const [found, setFound] = useState<CustomerBrief | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [memory, setMemory] = useState<MemoryLine[]>([]);
  const [said, setSaid] = useState('');

  const write = () => {
    setWriting(true); setError(null);
    writeBrief(customerId).then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  // What the seller told Compass: correct or add, and the brief is written again with it.
  const tell = () => {
    if (!said.trim()) return;
    remember(customerId, said, 'brief').then((lines) => { setMemory(lines); setSaid(''); write(); },
      (failure) => setError(errorText(failure)));
  };
  const drop = (lineId: string) => {
    forget(customerId, lineId).then((lines) => { setMemory(lines); setFound((kept) => (kept ? { ...kept, stale: true } : kept)); },
      (failure) => setError(errorText(failure)));
  };
  useEffect(() => {
    fetchMemory(customerId).then(setMemory, () => setMemory([]));
    fetchBrief(customerId).then((kept) => {
      setFound(kept);
      if (!kept.kept && kept.available) write();
    }, (failure) => setError(errorText(failure)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  if (error && !found?.markdown) return <div className="azure-cost-error">{error}</div>;
  if (!found || writing) {
    return <Loading label={writing ? 'Compass is writing the brief from this customer\'s figures and notes — this can take a minute…' : 'Loading…'} />;
  }
  if (!found.markdown) {
    return <p className="empty-state">{found.available ? 'No brief yet.' : 'Compass is not available to plugins on this install: the brief needs Compass configured (Settings > System) and a framework that offers it.'}</p>;
  }
  const copy = () => {
    try {
      void navigator.clipboard.writeText(found.markdown ?? '').then(() => setCopied(true));
    } catch { /* the clipboard may be blocked; the text is on screen */ }
  };
  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">
          Written {found.generated_at ? new Date(found.generated_at).toLocaleString() : ''} by Compass from this report's figures,
          its solutions and pitches, the pipeline and quota, and the vault's notes. Check before you quote it.
        </span>
        <button type="button" className="btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <button type="button" className="btn" disabled={writing || !found.available} onClick={write}>
          {writing ? 'Writing…' : 'Write again'}</button>
      </div>
      {found.stale ? <p className="azure-cost-warning">The data has changed since this brief was written. Write it again for the latest.</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-brief"><NoteText text={found.markdown} /></div>
      <section className="azure-cost-memory">
        <h4>What Compass knows from you</h4>
        {memory.length ? (
          <ul>
            {memory.map((line) => (
              <li key={line.id}>
                {line.said} <span className="text-muted">({line.on}{line.source !== 'you' && line.source !== 'brief' ? `, ${line.source}` : ''})</span>
                <button type="button" className="azure-cost-popup-close" onClick={() => drop(line.id)}
                        aria-label={`Forget: ${line.said}`} title="Forget this">✕</button>
              </li>
            ))}
          </ul>
        ) : <p className="text-muted">Nothing yet. What you tell it here, or answer in Explain this, is kept for this customer and used in every brief, explanation, draft and ranking.</p>}
        <form className="azure-cost-explain-reply" onSubmit={(event) => { event.preventDefault(); tell(); }}>
          <label className="field-labeled">Correct or add to it
            <textarea rows={2} value={said} onChange={(event) => setSaid(event.target.value)}
                      placeholder="e.g. The MACC was renewed at $150M in September; they are moving SAP this quarter" />
          </label>
          <button type="submit" className="btn btn-primary" disabled={!said.trim() || !found.available}>Remember and rewrite</button>
        </form>
      </section>
    </>
  );
}

export function BriefButton({ customerId, customerName }: { customerId: string; customerName: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}
              title="A brief before a meeting, written by Compass from this customer's data">Brief me</button>
      {open ? (
        <Popup kicker="Brief before a meeting" title={customerName} onClose={() => setOpen(false)} tall>
          <BriefBody customerId={customerId} />
        </Popup>
      ) : null}
    </>
  );
}
