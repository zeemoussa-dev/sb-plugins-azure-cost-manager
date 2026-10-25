import { useEffect, useState } from 'react';
import { NoteText } from '../../pluginHost/noteText';
import type { Kept } from './client';
import { errorText } from './format';
import { Loading } from './Loading';
import { Popup } from './Popup';

/** Whether a card is unfolded: the viewer's choice, kept in this browser across
 *  customers and visits. */
export function useRememberedFold(storageKey: string, foldedByDefault = false): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => {
    try {
      const kept = localStorage.getItem(storageKey);
      return kept === null ? !foldedByDefault : kept !== '1';
    } catch { return !foldedByDefault; }
  });
  const fold = (nowOpen: boolean) => {
    setOpen(nowOpen);
    try { localStorage.setItem(storageKey, nowOpen ? '0' : '1'); } catch { /* storage may be blocked */ }
  };
  return [open, fold];
}

interface KeptTextProps {
  read: () => Promise<Kept<string>>;
  write: () => Promise<Kept<string>>;
  /** Where the text comes from, above it: what Compass was handed. */
  source: string;
  writingLabel: string;
}

function KeptTextBody({ read, write: writeText, source, writingLabel }: KeptTextProps) {
  const [found, setFound] = useState<Kept<string> | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const write = () => {
    setWriting(true); setError(null);
    writeText().then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  useEffect(() => {
    read().then((kept) => {
      setFound(kept);
      if (!kept.kept && kept.available) write();
    }, (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error && !found?.value) return <div className="azure-cost-error">{error}</div>;
  if (!found || writing) return <Loading label={writing ? writingLabel : 'Loading…'} />;
  if (!found.value) {
    return <p className="empty-state">{found.available ? 'Nothing written yet.' : 'Compass is not available to plugins on this install.'}</p>;
  }
  const copy = () => {
    try {
      void navigator.clipboard.writeText(found.value ?? '').then(() => setCopied(true));
    } catch { /* the clipboard may be blocked; the text is on screen */ }
  };
  return (
    <>
      <div className="azure-cost-toolbar">
        <span className="text-muted azure-cost-note">{source}</span>
        <button type="button" className="btn" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <button type="button" className="btn" disabled={writing || !found.available} onClick={write}>Write again</button>
      </div>
      {found.stale ? <p className="azure-cost-warning">The findings have changed since. Write it again for the latest.</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-brief"><NoteText text={found.value} /></div>
    </>
  );
}

/** A button opening text Compass writes for the customer -- kept until the findings
 *  change, written on first opening, copyable. */
export function KeptTextButton({ label, hint, kicker, title, ...body }: KeptTextProps & {
  label: string; hint: string; kicker: string; title: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)} title={hint}>{label}</button>
      {open ? (
        <Popup kicker={kicker} title={title} onClose={() => setOpen(false)} tall>
          <KeptTextBody {...body} />
        </Popup>
      ) : null}
    </>
  );
}
