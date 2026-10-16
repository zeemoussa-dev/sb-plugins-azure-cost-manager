import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSyncStatus, startSync, type SyncStatus } from './client';
import { errorText } from './format';

const POLL_MS = 3000;

/** Starts the background sync -- for one customer, or every one -- and follows
 *  it. The weekly Hermes job starts the same sync; this shows it either way. */
export function SyncControl({ customerId, syncedAt, onSynced }: {
  customerId?: string; syncedAt?: string | null; onSynced: () => void;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);

  const poll = useCallback(() => {
    fetchSyncStatus().then((next) => {
      setStatus(next);
      if (wasRunning.current && !next.running) onSynced();
      wasRunning.current = next.running;
    }, (failure) => setError(errorText(failure)));
  }, [onSynced]);

  useEffect(() => {
    poll();
  }, [poll]);

  useEffect(() => {
    if (!status?.running) return undefined;
    const timer = window.setTimeout(poll, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [status, poll]);

  function start() {
    setError(null);
    startSync(customerId).then((next) => {
      wasRunning.current = true;
      setStatus(next);
      if (next.started === false && next.reason) setError(next.reason);
    }, (failure) => setError(errorText(failure)));
  }

  const running = status?.running;
  const current = status?.current;
  return (
    <div className="azure-cost-toolbar">
      <span className="text-muted">
        {running
          ? `Syncing ${status.accounts_done} of ${status.accounts_total || '?'} enrollments`
            + (current ? ` — ${current.account}, ${current.first_month} to ${current.last_month}` : '')
            + (current?.waiting_seconds ? ` (Azure asked to wait ${current.waiting_seconds}s)` : '')
          : syncedAt ? `Synced ${new Date(syncedAt).toLocaleString()}` : 'Not synced yet'}
      </span>
      {!running && status?.errors.length ? (
        <span className="azure-cost-warning" title={status.errors.map((e) => `${e.account ?? ''} ${e.message}`).join('\n')}>
          last sync: {status.errors.length} problem{status.errors.length === 1 ? '' : 's'}
        </span>
      ) : null}
      {error ? <span className="azure-cost-warning">{error}</span> : null}
      <button type="button" className="btn" onClick={start} disabled={running}>
        {running ? 'Syncing…' : customerId ? 'Sync this customer' : 'Sync all customers'}
      </button>
    </div>
  );
}
