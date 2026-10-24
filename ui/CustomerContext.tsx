import { useEffect, useState } from 'react';
import { draftCustomerContext, fetchCustomerContext, saveCustomerContext, type CustomerContext } from './client';
import { useRememberedFold } from './CompassText';
import { errorText } from './format';

/** Where the customer stands, as the seller knows it (operator, 2026-10-24: "where the
 *  customer is in digitalization, how the data is looking now -- a good input before
 *  recommending a solution"). Compass may draft it; only what is saved is used, by the
 *  brief, what to pitch, a use case and a draft. */
export function CustomerContextCard({ customerId, onSaved }: { customerId: string; onSaved?: () => void }) {
  const [kept, setKept] = useState<CustomerContext | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<'saving' | 'drafting' | null>(null);
  const [drafted, setDrafted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, fold] = useRememberedFold('azure-cost-manager.customer-context-folded');

  useEffect(() => {
    fetchCustomerContext(customerId).then((found) => { setKept(found); setFields(found.fields); setDrafted(false); },
      (failure) => setError(errorText(failure)));
  }, [customerId]);
  if (!kept) return error ? <div className="azure-cost-error">{error}</div> : null;

  const changed = kept.labels.some(({ key }) => (fields[key] ?? '') !== (kept.fields[key] ?? ''));
  const filled = kept.labels.filter(({ key }) => kept.fields[key]).length;
  const run = (kind: 'saving' | 'drafting', call: () => Promise<void>) => {
    setBusy(kind); setError(null);
    call().catch((failure) => setError(errorText(failure))).finally(() => setBusy(null));
  };
  return (
    <details className="card azure-cost-card azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head">
        <h3>Customer context</h3>
        <span className="text-muted">{filled ? `${filled} of ${kept.labels.length} filled${kept.updated ? `, ${kept.updated}` : ''}` : 'not filled'}</span>
        {/* preventDefault: a click on the button must not fold the card. */}
        <button type="button" className="btn" disabled={busy !== null}
                onClick={(event) => {
                  event.preventDefault(); fold(true);
                  run('drafting', () => draftCustomerContext(customerId).then((found) => { setFields(found.draft); setDrafted(true); }));
                }}
                title="Compass reads the reports and the vault and drafts it; nothing is saved until you save">
          {busy === 'drafting' ? 'Drafting…' : 'Draft with Compass'}</button>
      </summary>
      <p className="text-muted azure-cost-note">
        Where this customer stands. Compass treats it as fact when it briefs you, recommends what to pitch, writes a
        use case or drafts an opportunity — so a customer whose data is not ready gets the data foundation first.
      </p>
      {drafted ? <p className="azure-cost-warning">Compass's draft from the data: correct what you know better, then save.</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-context-fields">
        {kept.labels.map(({ key, label, hint }) => (
          <label key={key} className="field-labeled">{label}
            <textarea rows={2} value={fields[key] ?? ''} placeholder={hint}
                      onChange={(event) => setFields((current) => ({ ...current, [key]: event.target.value }))} />
          </label>
        ))}
      </div>
      <div className="azure-cost-toolbar">
        <button type="button" className="btn btn-primary" disabled={!changed || busy !== null}
                onClick={() => run('saving', () => saveCustomerContext(customerId, fields).then((found) => {
                  setKept(found); setFields(found.fields); setDrafted(false); onSaved?.();
                }))}>{busy === 'saving' ? 'Saving…' : 'Save'}</button>
        {changed ? <button type="button" className="btn" disabled={busy !== null}
                           onClick={() => { setFields(kept.fields); setDrafted(false); }}>Discard changes</button> : null}
      </div>
    </details>
  );
}
