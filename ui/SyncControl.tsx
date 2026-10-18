import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchSyncStatus, refreshThisMonth, startSync, startTagSync, type SyncStatus } from './client';
import { errorText, formatMonth } from './format';
import { SyncDetails } from './SyncDetails';

const POLL_MS = 3000;

type SyncKind = 'consumption' | 'tags' | 'daily';

const KIND_SUFFIX: Record<string, string> = { ':tags': ' — tags only', ':this-month': ' — daily data only' };

function scopeLabel(scope: string | null, customerId?: string): string {
  if (scope === 'profiles') return 'every billing profile that is no customer yet (invoice totals and Marketplace)';
  const suffix = Object.keys(KIND_SUFFIX).find((ending) => scope?.endsWith(ending));
  const unsuffixed = suffix ? scope!.slice(0, -suffix.length) : scope;
  const profiles = unsuffixed?.endsWith('+profiles');
  const base = profiles ? unsuffixed!.slice(0, -'+profiles'.length) : unsuffixed;
  const label = !base || base === 'all' ? 'all customers' : base === customerId ? 'this customer' : `customer “${base}”`;
  return (profiles ? `${label}, then every other billing profile` : label) + (suffix ? KIND_SUFFIX[suffix] : '');
}

/** Starts the background sync -- for one customer, or every one -- and follows
 *  it. The weekly Hermes job starts the same sync; this shows it either way.
 *
 *  A sync takes minutes (Azure throttles, and every billing month is its own
 *  call), so it is shown as a banner, and the page is refreshed each time an
 *  enrollment finishes rather than only at the end -- a quiet line of grey text
 *  read as a button that did nothing (operator, 2026-10-16). */
export function SyncControl({ customerId, syncedAt, onSynced, profiles = 'none', label, details = true }: {
  customerId?: string; syncedAt?: string | null; onSynced: () => void;
  profiles?: 'none' | 'also' | 'only'; label?: string;
  /** Off for a second control on the same page: one Sync details panel is enough. */
  details?: boolean;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);
  const accountsDone = useRef(0);

  const poll = useCallback(() => {
    fetchSyncStatus().then((next) => {
      setStatus(next);
      const finished = wasRunning.current && !next.running;
      const enrollmentFinished = next.running && next.accounts_done > accountsDone.current;
      if (finished || enrollmentFinished) onSynced();
      wasRunning.current = next.running;
      accountsDone.current = next.running ? next.accounts_done : 0;
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

  // Tags and daily data each on their own, without a full sync (operator, 2026-10-18).
  function start(kind: SyncKind = 'consumption') {
    setError(null);
    const started: Promise<SyncStatus> = kind === 'tags' ? startTagSync(customerId)
      : kind === 'daily' ? refreshThisMonth(customerId) : startSync(customerId, profiles);
    started.then((next) => {
      wasRunning.current = true;
      accountsDone.current = 0;
      setStatus(next);
      if (next.started === false && next.reason) {
        setError(`${next.reason} (${scopeLabel(next.scope, customerId)}) — wait for it to finish, then sync again.`);
      }
    }, (failure) => setError(errorText(failure)));
  }

  const running = status?.running;
  const current = status?.current;
  const total = status?.accounts_total || 0;
  const done = status?.accounts_done || 0;
  // Some stages carry no month range (this month by day, tags, pricing): a phase
  // without months must not take the page down (operator, 2026-10-18).
  const months = (from?: string, to?: string) => from
    ? `${formatMonth(from)}${to && to !== from ? ` to ${formatMonth(to)}` : ''}` : '';
  const phase = !current ? 'starting'
    : current.this_month ? 'fetching last month and this one, day by day'
      : current.pricing ? 'pricing steady on-demand meters'
        : current.tags ? `reading costs by tag${current.tag ? ` “${current.tag}”` : ''}${current.first_month ? `, ${months(current.first_month, current.last_month)}` : ''}`
          : current.amortized_meters ? `fetching amortized meters, ${months(current.first_month, current.last_month)}`
            : current.balances ? `reading the billing balance for ${months(current.first_month)}`
              : current.marketplace ? `reading Marketplace charges for ${months(current.first_month)}`
                : current.first_month ? `fetching ${months(current.first_month, current.last_month)}` : 'working';

  return (
    <>
      {running ? (
        <div className="azure-cost-sync-banner" role="status">
          <strong>Syncing {scopeLabel(status.scope, customerId)}</strong>
          <span>
            Enrollment {Math.min(done + 1, total || 1)} of {total || '?'}
            {current?.account ? ` (${current.display_name ? `${current.display_name}, ` : ''}${current.account})` : ''}: {phase}
            {current?.waiting_seconds ? ` — Azure asked to wait ${current.waiting_seconds}s` : ''}
          </span>
          <div className="azure-cost-sync-progress"><span style={{ width: `${total ? (done / total) * 100 : 5}%` }} /></div>
          <span className="text-muted">
            This takes a few minutes. The page fills in as each enrollment finishes; you can leave it and come back.
          </span>
        </div>
      ) : null}
      <div className="azure-cost-toolbar">
        <span className="text-muted">
          {running ? '' : syncedAt ? `Synced ${new Date(syncedAt).toLocaleString()}` : 'Not synced yet'}
        </span>
        {!running && status?.errors.length ? (
          <span className="azure-cost-warning" title={status.errors.map((e) => `${e.account ?? ''} ${e.message}`).join('\n')}>
            last sync: {status.errors.length} problem{status.errors.length === 1 ? '' : 's'}
          </span>
        ) : null}
        {error ? <span className="azure-cost-warning">{error}</span> : null}
        <button type="button" className="btn" onClick={() => start()} disabled={running}>
          {running ? 'Syncing…' : label ?? (customerId ? 'Sync this customer' : 'Sync all customers')}
        </button>
        {profiles === 'only' ? null : (
          <>
            <button type="button" className="btn" onClick={() => start('tags')} disabled={running}
                    title="Cost by tag (Project, Owner, Environment...) only, without a full sync">
              Sync tags
            </button>
            <button type="button" className="btn" onClick={() => start('daily')} disabled={running}
                    title="Last month and this one by day (the This month report) only, without a full sync">
              Sync daily data
            </button>
          </>
        )}
      </div>
      {details ? <SyncDetails status={status} /> : null}
    </>
  );
}
