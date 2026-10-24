import { useEffect, useState } from 'react';
import {
  fetchPersonas, generatePersona, resetPersona, savePersona, type Persona, type PersonasState,
} from './client';
import { errorText } from './format';
import { Loading } from './Loading';

function PersonaEditor({ persona, available, onChanged }: {
  persona: Persona; available: boolean; onChanged: (state: PersonasState) => void;
}) {
  const [text, setText] = useState(persona.prompt);
  const [wish, setWish] = useState('');
  const [busy, setBusy] = useState<'saving' | 'drafting' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafted, setDrafted] = useState(false);
  useEffect(() => { setText(persona.prompt); setDrafted(false); }, [persona.prompt]);

  const run = (kind: 'saving' | 'drafting', call: () => Promise<void>) => {
    setBusy(kind); setError(null);
    call().catch((failure) => setError(errorText(failure))).finally(() => setBusy(null));
  };
  const changed = text.trim() !== persona.prompt.trim();
  return (
    <section className="card azure-cost-card">
      <div className="azure-cost-card-head">
        <h3>{persona.name}</h3>
        <span className="text-muted">{persona.serves.join(' · ')}{persona.edited ? ' · edited' : ''}</span>
      </div>
      <label className="field-labeled">Who Compass is here
        <textarea rows={6} value={text} onChange={(event) => { setText(event.target.value); setDrafted(false); }} />
      </label>
      {drafted ? <p className="azure-cost-warning">Compass's draft: read it, change what you want, then save.</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-toolbar">
        <button type="button" className="btn btn-primary" disabled={!changed || busy !== null}
                onClick={() => run('saving', () => savePersona(persona.id, text).then(onChanged))}>
          {busy === 'saving' ? 'Saving…' : 'Save'}</button>
        <button type="button" className="btn" disabled={!persona.edited || busy !== null}
                onClick={() => run('saving', () => resetPersona(persona.id).then(onChanged))}
                title="Back to the persona Azure Customer 360 ships">Reset to shipped</button>
      </div>
      <form className="azure-cost-explain-reply" onSubmit={(event) => {
        event.preventDefault();
        run('drafting', () => generatePersona(persona.id, wish).then((found) => { setText(found.draft); setDrafted(true); }));
      }}>
        <label className="field-labeled">Ask Compass to draft it
          <input type="text" value={wish} onChange={(event) => setWish(event.target.value)}
                 placeholder="e.g. Think like a banking practice lead; push for conversations with the CFO and CRO" />
        </label>
        <button type="submit" className="btn" disabled={!available || busy !== null}
                title={available ? 'Compass drafts it; nothing is saved until you save' : 'Compass is not available to plugins on this install'}>
          {busy === 'drafting' ? 'Drafting…' : 'Draft with Compass'}</button>
      </form>
    </section>
  );
}

/** Who Compass is in each feature (operator, 2026-10-24): the editable part of its system
 *  prompts. What each feature must answer, and the rules that keep it to the plugin's
 *  figures, stay fixed underneath. */
export function PersonasCard() {
  const [state, setState] = useState<PersonasState | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { fetchPersonas().then(setState, (failure) => setError(errorText(failure))); }, []);
  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!state) return <Loading />;
  return (
    <>
      <section className="card azure-cost-card">
        <h3>Compass personas</h3>
        <p className="text-muted azure-cost-note">
          Who Compass is in each feature, and how it brings a customer's industry into its judgment. The facts it is
          given, the plugin's figures and each feature's answer format are fixed underneath, so editing a persona
          changes the voice and the judgment, never the numbers. Changing one marks what it wrote before as out of
          date.
        </p>
        <p className="text-muted azure-cost-note">
          Industries come from each Customer note's <code>industry</code> field, naming a note under Work/Industries
          {state.industries.length ? ` (${state.industries.length} in the vault: ${state.industries.join(', ')})` : ''}.
          A customer without one still works; the brief and pitches say that setting it is recommended.
        </p>
      </section>
      {state.personas.map((persona) => (
        <PersonaEditor key={persona.id} persona={persona} available={state.available} onChanged={setState} />
      ))}
    </>
  );
}
