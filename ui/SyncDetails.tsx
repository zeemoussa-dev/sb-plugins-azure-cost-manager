import { useCallback, useEffect, useState } from 'react';
import { fetchSyncLog, fetchSyncRun, type SyncEvent, type SyncRun, type SyncStatus } from './client';
import { errorText } from './format';

const POLL_MS = 3000;
const EVENTS_SHOWN = 200;

function seconds(from: string, to?: string | null): number {
  return Math.max(0, Math.round(((to ? Date.parse(to) : Date.now()) - Date.parse(from)) / 1000));
}

function duration(total: number): string {
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m ${total % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function time(at: string): string {
  return new Date(at).toLocaleTimeString();
}

/** What the sync is doing and has done, read from its on-disk log -- why a sync
 *  "gets stuck" (operator, 2026-10-18): the step and the Azure request in
 *  progress with how long each has taken, and the last runs, each with its
 *  requests, throttle waits and errors. A run the backend stopped by restarting
 *  shows as interrupted, at the last thing it did. */
export function SyncDetails({ status }: { status: SyncStatus | null }) {
  const [open, setOpen] = useState(false);
  const [runs, setRuns] = useState<(SyncRun & { events: number })[]>([]);
  const [chosen, setChosen] = useState<string | null>(null);
  const [events, setEvents] = useState<SyncEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [, tick] = useState(0);
  const running = Boolean(status?.running);

  const load = useCallback(() => {
    fetchSyncLog().then((found) => {
      setRuns(found.runs);
      setError(null);
      const runId = chosen ?? found.runs[0]?.id;
      if (!runId) { setEvents([]); return; }
      fetchSyncRun(runId, EVENTS_SHOWN).then((run) => setEvents(run.events), (failure) => setError(errorText(failure)));
    }, (failure) => setError(errorText(failure)));
  }, [chosen]);

  useEffect(() => {
    if (!open) return undefined;
    load();
    if (!running) return undefined;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [open, running, load]);

  // The elapsed times count up between polls.
  useEffect(() => {
    if (!open || !running) return undefined;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [open, running]);

  const shownRun = runs.find((run) => run.id === (chosen ?? runs[0]?.id));

  return (
    <details className="card azure-cost-card azure-cost-fold azure-cost-sync-details"
             onToggle={(event) => setOpen((event.target as HTMLDetailsElement).open)}>
      <summary><h3>Sync details</h3></summary>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {running && status ? (
        <dl className="azure-cost-sync-now">
          <dt>Running for</dt>
          <dd>{status.started_at ? duration(seconds(status.started_at)) : '—'}</dd>
          <dt>This step</dt>
          <dd>{status.step_started_at ? duration(seconds(status.step_started_at)) : '—'}
            {status.current?.waiting_seconds ? ` (waiting ${status.current.waiting_seconds}s for Azure)` : ''}</dd>
          <dt>Azure request</dt>
          <dd>{status.in_flight
            ? <>{status.in_flight.what} — <strong>{duration(seconds(status.in_flight.since))}</strong> on the wire</>
            : 'none in progress'}</dd>
        </dl>
      ) : null}

      {runs.length ? (
        <table className="azure-cost-table">
          <thead><tr><th>Started</th><th>Scope</th><th>Took</th><th>Outcome</th><th>Requests</th><th>Pages</th>
            <th>Throttle waits</th><th>Errors</th></tr></thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className={run.id === shownRun?.id ? 'selected' : undefined}>
                <td><button type="button" className="btn azure-cost-link-button" onClick={() => setChosen(run.id)}>
                  {new Date(run.started_at).toLocaleString()}</button></td>
                <td>{run.scope}</td>
                <td>{duration(seconds(run.started_at, run.finished_at))}</td>
                <td className={run.outcome === 'interrupted' || run.outcome === 'stopped' ? 'azure-cost-warning' : undefined}>
                  {run.outcome}</td>
                <td>{run.requests}</td>
                <td>{run.pages}</td>
                <td>{run.throttle_waits ? `${run.throttle_waits} (${duration(run.waited_seconds)})` : 0}</td>
                <td>{run.errors}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="text-muted">No sync has run since the log began.</p>}

      {shownRun ? (
        <>
          <h4>Run of {new Date(shownRun.started_at).toLocaleString()} — newest first
            {shownRun.events > EVENTS_SHOWN ? `, last ${EVENTS_SHOWN} of ${shownRun.events}` : ''}</h4>
          <ol className="azure-cost-sync-events">
            {[...events].reverse().map((event, index) => (
              <li key={`${event.at}-${index}`} className={`kind-${event.kind}`}>
                <span className="text-muted">{time(event.at)}</span> <span className="azure-cost-sync-kind">{event.kind}</span>{' '}
                {event.text}
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </details>
  );
}
