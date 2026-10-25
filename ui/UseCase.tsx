import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { apiFetch } from '../../pluginHost/api';
import { NoteText } from '../../pluginHost/noteText';
import { fetchUseCase, publishUseCase, remember, writeUseCase, type UseCaseDetails } from './client';
import { errorText } from './format';
import { Loading } from './Loading';
import { Popup } from './Popup';

/** The note's body without its frontmatter, as it will read in the vault. */
function bodyOf(markdown: string): string {
  return markdown.startsWith('---') ? markdown.slice(markdown.indexOf('\n---', 3) + 4).trim() : markdown;
}

function UseCaseBody({ customerId, customerName, pitch, onPublished }: {
  customerId: string; customerName: string; pitch: string; onPublished: (stem: string) => void;
}) {
  const [found, setFound] = useState<UseCaseDetails | null>(null);
  const [busy, setBusy] = useState<'writing' | 'publishing' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState('');
  const write = () => {
    setBusy('writing'); setError(null);
    writeUseCase(customerId, pitch).then(setFound, (failure) => setError(errorText(failure))).finally(() => setBusy(null));
  };
  const publish = () => {
    setBusy('publishing'); setError(null);
    publishUseCase(customerId, pitch).then((published) => {
      setFound(published);
      if (published.use_case_note) onPublished(published.use_case_note);
      // The framework's own index learns of the new note now, not at its next scan.
      apiFetch('/vault-index/refresh', { method: 'POST' }).catch(() => undefined);
    }, (failure) => setError(errorText(failure))).finally(() => setBusy(null));
  };
  useEffect(() => {
    fetchUseCase(customerId, pitch).then((kept) => {
      setFound(kept);
      if (!kept.kept && kept.available) write();
    }, (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, pitch]);

  if (error && !found?.value) return <div className="azure-cost-error">{error}</div>;
  if (!found || busy === 'writing') {
    return <Loading label={busy === 'writing' ? 'Compass is writing the use case out — this can take a minute…' : 'Loading…'} />;
  }
  if (!found.value) {
    return <p className="empty-state">{found.available ? 'Not written yet.' : 'Compass is not available to plugins on this install.'}</p>;
  }
  const mine = found.value.for_this_customer;
  // What the seller adds goes into the customer's memory -- every feature reads it -- then this is written again.
  const refine = () => {
    if (!said.trim()) return;
    remember(customerId, said, 'use case').then(() => { setSaid(''); write(); }, (failure) => setError(errorText(failure)));
  };
  const canPublish = !found.use_case_note && found.industry_note && found.note_markdown;
  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">
          Written by Compass from the {found.industry ? `${found.industry} industry note` : 'facts'}
          {found.solution_note ? `, the ${found.solution_note} Solution note` : ''} and this customer's data. Check before you quote it.
        </span>
        <button type="button" className="btn" disabled={busy !== null || !found.available} onClick={write}>Write again</button>
        {found.use_case_note ? (
          <Link className="btn" to={`/browse/${encodeURIComponent(found.use_case_note)}`}>Open in the vault</Link>
        ) : (
          <button type="button" className="btn btn-primary" disabled={!canPublish || busy !== null} onClick={publish}
                  title={canPublish ? `Files it as a use-case note under ${found.industry}, linked to its Solution note`
                    : 'Set the customer\'s industry, with an Industry note in the vault, to publish it'}>
            {busy === 'publishing' ? 'Publishing…' : 'Publish to vault'}</button>
        )}
      </div>
      {found.stale ? <p className="azure-cost-warning">What this was written from has changed. Write it again for the latest.</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {found.use_case_note ? (
        <p className="text-muted azure-cost-note">In the vault as <strong>{found.use_case_note}</strong>, under {found.industry}'s use cases.</p>
      ) : !found.industry ? (
        <p className="text-muted azure-cost-note">This customer has no industry set on its Customer note, so the use case cannot be filed under one.</p>
      ) : null}
      <section className="azure-cost-memory">
        <h4>For {customerName}</h4>
        {mine.why_them ? <NoteText text={mine.why_them} /> : null}
        {mine.how_to_pitch_them ? <p><strong>How to pitch them:</strong> {mine.how_to_pitch_them}</p> : null}
        {found.value.note.expected_services?.length ? (
          <table className="azure-cost-table">
            <thead><tr><th>Expected service</th><th>Role</th><th /><th>On {customerName}'s bill</th></tr></thead>
            <tbody>
              {found.value.note.expected_services.map((item) => (
                <tr key={item.service}>
                  <td>{item.service}</td><td>{item.role}</td>
                  <td className="text-muted">{item.core ? 'core' : 'add-on'}</td>
                  <td className={found.on_the_bill?.[item.service] === 'running' ? undefined : 'text-muted'}>
                    {found.on_the_bill?.[item.service] ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {mine.first_step ? <p><strong>First step:</strong> {mine.first_step}</p> : null}
        {mine.questions.length ? <ul>{mine.questions.map((question) => <li key={question}>{question}</li>)}</ul> : null}
        <form className="azure-cost-explain-reply" onSubmit={(event) => { event.preventDefault(); refine(); }}>
          <label className="field-labeled">Refine: what Compass should know
            <textarea rows={2} value={said} onChange={(event) => setSaid(event.target.value)}
                      placeholder="e.g. Their alert data sits in Actimize on-premises; Compliance owns the budget, not IT" />
          </label>
          <button type="submit" className="btn" disabled={!said.trim() || busy !== null || !found.available}>Remember and rewrite</button>
        </form>
        <p className="text-muted azure-cost-note">
          Where the customer stands (digital maturity, data today, cloud, AI readiness) is set in Customer context on the
          Solutions tab; what you add here is kept in its memory.
        </p>
      </section>
      <h4>The use case{found.use_case_note ? '' : ', as it would be filed'}</h4>
      <div className="azure-cost-brief">
        <NoteText text={found.note_markdown ? bodyOf(found.note_markdown) : found.value.note.summary} />
      </div>
    </>
  );
}

/** A Compass pitch's use case, drilled into (operator, 2026-10-24): the details, and
 *  the note to publish to the vault when there is none for it yet. */
export function UseCaseButton({ customerId, customerName, pitch, label, onPublished }: {
  customerId: string; customerName: string; pitch: string; label: string; onPublished: (stem: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="azure-cost-link-button" onClick={() => setOpen(true)}
              title="The use case in detail, and its note for the vault">{label}</button>
      {open ? (
        <Popup kicker="Industry use case" title={label} onClose={() => setOpen(false)} tall>
          <UseCaseBody customerId={customerId} customerName={customerName} pitch={pitch} onPublished={onPublished} />
        </Popup>
      ) : null}
    </>
  );
}
