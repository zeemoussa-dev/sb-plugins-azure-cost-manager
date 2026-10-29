import { useEffect, useState } from 'react';
import { SeriesChart } from './charts';
import { fetchSubscriptionGroups, saveSubscriptionGroups, type SubscriptionGroup, type SubscriptionGroupsReport } from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';

/** One line per group in the editor: its name, and the name fragments that put a subscription in it. */
interface DraftRow { name: string; match: string }

const toDraft = (groups: SubscriptionGroup[]): DraftRow[] => groups.map((group) => ({ name: group.name, match: group.match.join(', ') }));
const fromDraft = (rows: DraftRow[]): SubscriptionGroup[] => rows
  .filter((row) => row.name.trim() || row.match.trim())
  .map((row) => ({ name: row.name.trim(), match: row.match.split(',').map((part) => part.trim()).filter(Boolean) }));

/** The customer's own groups of subscriptions by name (operator, 2026-10-29: "how much M42
 *  spends on storage regarding Genome"), per month, on every service or just one. */
export function SubscriptionGroups({ customerId, accounts, syncedVersion }: {
  customerId: string; accounts?: string[]; syncedVersion: number;
}) {
  const [service, setService] = useState<string | null>(null);
  const [found, setFound] = useState<SubscriptionGroupsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<DraftRow[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [version, setVersion] = useState(0);
  const accountsKey = accounts?.join(',') ?? '';

  useEffect(() => {
    fetchSubscriptionGroups(customerId, service, accountsKey ? accountsKey.split(',') : undefined)
      .then((result) => { setFound(result); setError(null); }, (failure) => setError(errorText(failure)));
  }, [customerId, service, accountsKey, syncedVersion, version]);

  const save = () => {
    if (!draft) return;
    setSaving(true);
    saveSubscriptionGroups(customerId, fromDraft(draft))
      .then(() => { setDraft(null); setError(null); setVersion((value) => value + 1); },
        (failure) => setError(errorText(failure)))
      .finally(() => setSaving(false));
  };

  const currency = found?.currency ?? null;
  const months = found?.months ?? [];
  const latest = months.length > 1 ? months.slice(-4) : months;
  const groups = found?.groups ?? [];

  return (
    <section className="card azure-cost-card azure-cost-wide">
      <div className="azure-cost-card-head">
        <h3>Subscription groups</h3>
        <div>
          {groups.length ? (
            <select value={service ?? ''} onChange={(event) => setService(event.target.value || null)} aria-label="Service">
              <option value="">All services</option>
              {(found?.services ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          ) : null}{' '}
          {draft ? null : (
            <button type="button" className="btn" onClick={() => setDraft(toDraft(groups.length ? groups : []).concat([{ name: '', match: '' }]))}>
              {groups.length ? 'Edit groups' : 'Add a group'}
            </button>
          )}
        </div>
      </div>
      {error ? <p className="azure-cost-error">{error}</p> : null}

      {draft ? (
        <div className="azure-cost-groups-editor">
          <p className="text-muted azure-cost-note">A subscription belongs to the first group one of whose words its name contains, in any case (e.g. <em>EGP, genom</em>).</p>
          {draft.map((row, index) => (
            <div key={index} className="azure-cost-groups-row">
              <input type="text" placeholder="Group name" value={row.name} aria-label="Group name"
                     onChange={(event) => setDraft(draft.map((other, at) => (at === index ? { ...other, name: event.target.value } : other)))} />
              <input type="text" placeholder="Names containing, comma-separated" value={row.match} aria-label="Names containing"
                     onChange={(event) => setDraft(draft.map((other, at) => (at === index ? { ...other, match: event.target.value } : other)))} />
              <button type="button" className="btn" onClick={() => setDraft(draft.filter((_, at) => at !== index))}>Remove</button>
            </div>
          ))}
          <div className="azure-cost-groups-row">
            <button type="button" className="btn" onClick={() => setDraft([...draft, { name: '', match: '' }])}>Add a group</button>
            <button type="button" className="btn btn-primary" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button>
            <button type="button" className="btn" onClick={() => setDraft(null)}>Cancel</button>
          </div>
        </div>
      ) : null}

      {!groups.length && !draft ? (
        <p className="text-muted">No groups yet. Group subscriptions by name, e.g. a programme whose subscriptions share a prefix, to see what it spends on each service.</p>
      ) : null}

      {groups.length && months.length ? (
        <>
          <SeriesChart label={`Subscription groups by month${service ? `, ${service}` : ''}`} currency={currency} height={280}
                       categories={months} categoryLabel={(month) => formatMonth(month, true)}
                       series={groups.map((group, index) => ({ name: group.name, stack: 'groups', color: index,
                         data: months.map((month) => group.monthly[month] ?? 0) }))} />
          <table className="azure-cost-table">
            <thead>
              <tr><th>{service ?? 'All services'}</th>{latest.map((month) => <th key={month}>{formatMonth(month, true)}</th>)}</tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <GroupRows key={group.name} group={group} months={latest} currency={currency} />
              ))}
            </tbody>
          </table>
          <p className="text-muted azure-cost-note">Actual cost from the subscription × service split; the current month is still running.</p>
        </>
      ) : null}
    </section>
  );
}

function GroupRows({ group, months, currency }: {
  group: SubscriptionGroupsReport['groups'][number]; months: string[]; currency: string | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr>
        <td>
          <button type="button" className="btn azure-cost-link-button" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? '▾' : '▸'} <strong>{group.name}</strong>
          </button>{' '}
          <span className="text-muted">{group.subscriptions.length} subscriptions · {group.match.join(', ')}</span>
        </td>
        {months.map((month) => <td key={month}><strong>{formatMoney(group.monthly[month] ?? 0, currency)}</strong></td>)}
      </tr>
      {open ? group.subscriptions.map((subscription) => (
        <tr key={subscription.name}>
          <td className="azure-cost-groups-sub"><DrillLink kind="subscription" name={subscription.name} /></td>
          {months.map((month) => <td key={month}>{formatMoney(subscription.monthly[month] ?? 0, currency)}</td>)}
        </tr>
      )) : null}
    </>
  );
}
