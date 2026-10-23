import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import { fetchDrill, type Drill, type DrillKind } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink, type Report } from './ReportsHome';

const KIND_LABELS: Record<DrillKind, string> = {
  service: 'Service', subscription: 'Subscription', play: 'Solution play', month: 'Month',
};
const KINDS = Object.keys(KIND_LABELS) as DrillKind[];

/** `drill=<kind>:<name>` in the URL: what is opened, kept across a refresh and undone by Back. */
export function useDrillState(): [{ kind: DrillKind; name: string } | null, (kind: DrillKind, name: string) => void, () => void] {
  const [raw, setRaw] = useUrlState<string>('drill', '', { history: 'push' });
  const at = raw.indexOf(':');
  const kind = raw.slice(0, at) as DrillKind;
  const opened = at > 0 && KINDS.includes(kind) ? { kind, name: raw.slice(at + 1) } : null;
  return [opened, (next, name) => setRaw(`${next}:${name}`), () => setRaw('')];
}

const DrillContext = createContext<((kind: DrillKind, name: string) => void) | null>(null);

export function DrillProvider({ open, children }: { open: (kind: DrillKind, name: string) => void; children: ReactNode }) {
  return <DrillContext.Provider value={open}>{children}</DrillContext.Provider>;
}

/** Opens a drill from a chart or table inside a customer's report; nothing outside one. */
export function useDrillOpener(): ((kind: DrillKind, name: string) => void) | null {
  return useContext(DrillContext);
}

/** A customer's report with something drilled into, for a link from another page. */
export function drillLink(customerId: string, kind: DrillKind, name: string, report: Report = 'Breakdown'): string {
  return `${reportLink(report, customerId)}&drill=${encodeURIComponent(`${kind}:${name}`)}`;
}

/** Any service, subscription, play or month shown as text: inside a customer's report
 *  it opens the drill there; elsewhere, given the customer, it links to one. */
export function DrillLink({ kind, name, customerId, report, children }: {
  kind: DrillKind; name: string; customerId?: string; report?: Report; children?: ReactNode;
}) {
  const open = useDrillOpener();
  const label = children ?? (kind === 'month' ? formatMonth(name) : name);
  if (customerId) return <Link to={drillLink(customerId, kind, name, report)} title={`Open ${name}`}>{label}</Link>;
  if (!open) return <>{label}</>;
  return (
    <button type="button" className="azure-cost-drill-link" title={`Open ${name}`}
            onClick={(event) => { event.stopPropagation(); open(kind, name); }}>{label}</button>
  );
}

function NoteLink({ stem, children }: { stem: string | null | undefined; children: ReactNode }) {
  return stem ? <Link to={`/browse/${encodeURIComponent(stem)}`}>{children}</Link> : null;
}

/** What is drilled into: its months (each opens that month) and what it is made of,
 *  every name opening further. */
export function DrillPanel({ customerId, accounts, opened, onClose }: {
  customerId: string; accounts: string[] | null; opened: { kind: DrillKind; name: string }; onClose: () => void;
}) {
  const open = useDrillOpener();
  const [drill, setDrill] = useState<Drill | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDrill(null); setError(null);
    fetchDrill(customerId, opened.kind, opened.name, accounts).then(setDrill, (failure) => setError(errorText(failure)));
  }, [customerId, opened.kind, opened.name, accounts?.join(',')]);

  const money = (value: number) => formatMoney(value, drill?.currency ?? null, true);
  return (
    <section className="card azure-cost-card azure-cost-drill" aria-label={`${KIND_LABELS[opened.kind]} ${opened.name}`}>
      <header className="azure-cost-drill-header">
        <div>
          <span className="azure-cost-kpi-label">{KIND_LABELS[opened.kind]}</span>
          <h3>{opened.kind === 'month' ? formatMonth(opened.name) : opened.name}</h3>
        </div>
        <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close">Close</button>
      </header>
      {error ? <div className="azure-cost-error">{error}</div> : !drill ? <p className="text-muted">Loading…</p> : (
        <>
          <p className="azure-cost-note">
            {drill.play ? <>Solution play: <DrillLink kind="play" name={drill.play} />. </> : null}
            {drill.technology_note ? <NoteLink stem={drill.technology_note}>Read about it: {drill.technology_note}</NoteLink> : null}
            {drill.kind === 'service' && !drill.technology_note ? <span className="text-muted">No Technology note in the vault for this service yet.</span> : null}
          </p>
          {drill.solutions?.length ? (
            <p className="azure-cost-note">
              Solutions: {drill.solutions.map((item, index) => (
                <span key={item.id}>{index ? ', ' : ''}{item.note ? <NoteLink stem={item.note}>{item.name}</NoteLink> : item.name}</span>
              ))}
            </p>
          ) : null}

          {drill.kind === 'month' ? (
            <>
              <p className="azure-cost-note">
                {money(drill.total ?? 0)} in services
                {drill.previous ? <> · against <DrillLink kind="month" name={drill.previous} /></> : null}
              </p>
              <div className="azure-cost-columns">
                <table className="azure-cost-table">
                  <thead><tr><th>Service</th><th>This month</th><th>Month before</th></tr></thead>
                  <tbody>
                    {(drill.parts as { name: string; cost: number; before: number }[]).slice(0, 25).map((row) => (
                      <tr key={row.name}><td><DrillLink kind="service" name={row.name} /></td>
                        <td>{money(row.cost)}</td><td className="text-muted">{money(row.before)}</td></tr>
                    ))}
                  </tbody>
                </table>
                <table className="azure-cost-table">
                  <thead><tr><th>Subscription</th><th>This month</th></tr></thead>
                  <tbody>
                    {(drill.subscriptions ?? []).slice(0, 25).map((row) => (
                      <tr key={row.name}><td><DrillLink kind="subscription" name={row.name} /></td><td>{money(row.cost)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {drill.by_play?.length ? (
                <p className="azure-cost-note">By solution play: {drill.by_play.map((row, index) => (
                  <span key={row.name}>{index ? ' · ' : ''}<DrillLink kind="play" name={row.name} /> {money(row.cost)}</span>
                ))}</p>
              ) : null}
            </>
          ) : (
            <>
              {drill.trend?.length ? (
                <SeriesChart categories={drill.trend.map((point) => point.month)} currency={drill.currency}
                             label={`${opened.name} by month`} height={200}
                             categoryLabel={(month) => formatMonth(month, true)}
                             series={[{ name: opened.name, data: drill.trend.map((point) => point.cost) }]}
                             onPick={open ? (month) => open('month', month) : undefined} />
              ) : null}
              {drill.marketplace?.length ? (
                <>
                  <h4>What {opened.name} is: the Marketplace products behind it</h4>
                  <p className="text-muted azure-cost-note">
                    Cost Management bills every Marketplace offer as "{opened.name}"; the Marketplace charges name each one.
                    Monthly average over the last closed months.
                  </p>
                  <table className="azure-cost-table">
                    <thead><tr><th>Publisher</th><th>Offer</th><th>Plan</th><th>Subscriptions</th><th>Monthly</th></tr></thead>
                    <tbody>
                      {drill.marketplace.map((row) => (
                        <tr key={`${row.publisher}|${row.offer}|${row.plan}`}>
                          <td>{row.publisher}</td><td>{row.offer}</td><td className="text-muted">{row.plan}</td>
                          <td>{row.subscriptions.map((sub, index) => (
                            <span key={sub}>{index ? ', ' : ''}<DrillLink kind="subscription" name={sub} /></span>))}</td>
                          <td>{money(row.monthly)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              ) : null}
              <h4>{drill.parts_kind === 'subscription' ? 'Subscriptions running it' : 'Services in it'}</h4>
              {drill.pairs_missing ? (
                <p className="text-muted azure-cost-note">
                  Some months were synced before services were kept by subscription; the next Sync all fills them in.
                </p>
              ) : null}
              {drill.parts.length ? (
                <table className="azure-cost-table">
                  <thead><tr><th>{drill.parts_kind === 'subscription' ? 'Subscription' : 'Service'}</th>
                    <th>Monthly, last {drill.recent_months?.length ?? 3}</th><th>Last 12 months</th>
                    {drill.parts_kind === 'service' ? <th /> : null}</tr></thead>
                  <tbody>
                    {(drill.parts as { name: string; monthly: number; last_12: number; technology_note?: string | null }[]).slice(0, 40).map((row) => (
                      <tr key={row.name}>
                        <td><DrillLink kind={drill.parts_kind} name={row.name} /></td>
                        <td>{money(row.monthly)}</td><td>{money(row.last_12)}</td>
                        {drill.parts_kind === 'service' ? <td><NoteLink stem={row.technology_note}>About it</NoteLink></td> : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="text-muted">Nothing in the last twelve closed months.</p>}
              {drill.resource_groups?.length ? (
                <p className="azure-cost-note">Resource groups: {drill.resource_groups.map((group) =>
                  `${group.name} ${money(group.monthly)}`).join(' · ')}</p>
              ) : null}
            </>
          )}
        </>
      )}
    </section>
  );
}
