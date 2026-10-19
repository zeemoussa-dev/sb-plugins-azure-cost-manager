import { useEffect, useMemo, useState } from 'react';
import { SeriesChart } from './charts';
import {
  createAffiliateNote, createOpportunity, fetchEntityCustomers, findHub, flattenHubs, saveCustomer, updateOpportunity,
  type Analysis, type EntityCustomer, type Opportunity, type PlanMonth,
} from './client';
import { errorText, formatMoney, formatMonth } from './format';

// The Opportunity Template's own values (Entities plugin).
const STATUSES = ['Open', 'Won', 'Lost', 'On Hold', 'Disengaged'];
const STAGES = ['Identified', 'Qualified', 'Proposed', 'Committed', 'Closed'];

function addMonths(month: string, count: number): string {
  const [year, number] = month.split('-').map(Number);
  const index = year * 12 + number - 1 + count;
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, '0')}`;
}

/** A plan the way the operator's Pipeline sheet reads: from a start month, a
 *  linear ramp up to a steady monthly figure, held to the end of the horizon. */
function rampPlan(start: string, steady: number, rampMonths: number, through: string): PlanMonth[] {
  const plan: PlanMonth[] = [];
  for (let step = 0, month = start; month <= through && step < 120; step += 1, month = addMonths(month, 1)) {
    const share = rampMonths > 0 ? Math.min((step + 1) / rampMonths, 1) : 1;
    plan.push({ month, usd: Math.round(steady * share) });
  }
  return plan;
}

interface Draft {
  id: string | null;
  owner: string;
  title: string;
  status: string;
  stage: string;
  partner: string;
  billing_profile: string;
  start: string;
  steady: number;
  ramp: number;
  plan: PlanMonth[];
}

function draftOf(opportunity: Opportunity | null, owner: string, horizon: string): Draft {
  const plan = opportunity?.plan ?? [];
  const start = opportunity?.consumption_start || plan[0]?.month || addMonths(new Date().toISOString().slice(0, 7), 1);
  return {
    id: opportunity?.id ?? null, owner, title: opportunity?.title ?? '', status: opportunity?.status ?? 'Open',
    stage: opportunity?.stage ?? 'Identified', partner: (opportunity?.partner ?? []).join(', '),
    billing_profile: opportunity?.billing_profile ?? '', start,
    steady: Number(opportunity?.expected_monthly_usd || plan[plan.length - 1]?.usd || 0), ramp: 3,
    plan: plan.length ? plan : rampPlan(start, 0, 3, horizon),
  };
}

function Editor({ analysis, owners, initial, onDone }: {
  analysis: Analysis; owners: { stem: string; name: string }[]; initial: Draft; onDone: (saved: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const horizon = `${new Date().getFullYear() + 1}-12`;

  function regenerate(next: Partial<Draft>) {
    const merged = { ...draft, ...next };
    setDraft({ ...merged, plan: rampPlan(merged.start, merged.steady, merged.ramp, horizon) });
  }

  function save() {
    setSaving(true);
    setError(null);
    const plan = draft.plan.filter((row) => row.usd);
    // Each partner must be a Partner note's name; the Entities plugin says which one is not.
    const partner = draft.partner.split(',').map((name) => name.trim()).filter(Boolean);
    const fields = { status: draft.status, stage: draft.stage, partner,
      billing_profile: draft.billing_profile, consumption_start: draft.start,
      expected_monthly_usd: plan.length ? plan[plan.length - 1].usd : 0 };
    const request = draft.id
      ? updateOpportunity(draft.id, fields, plan)
      : createOpportunity(analysis.customer.id, draft.owner, draft.title.trim(), fields, plan);
    request.then(() => { setSaving(false); onDone(true); }, (failure) => { setSaving(false); setError(errorText(failure)); });
  }

  return (
    <section className="card azure-cost-card azure-cost-editor">
      <h3>{draft.id ? `Plan ${draft.title}` : 'New opportunity'}</h3>
      <div className="azure-cost-form-row">
        {!draft.id ? (
          <>
            <label className="field-labeled">Under
              <select value={draft.owner} onChange={(event) => setDraft({ ...draft, owner: event.target.value })}>
                {owners.map((owner) => <option key={owner.stem} value={owner.stem}>{owner.name}</option>)}
              </select>
            </label>
            <label className="field-labeled">Title
              <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
            </label>
          </>
        ) : null}
        <label className="field-labeled">Status
          <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
            {STATUSES.map((status) => <option key={status}>{status}</option>)}
          </select>
        </label>
        <label className="field-labeled">Stage
          <select value={draft.stage} onChange={(event) => setDraft({ ...draft, stage: event.target.value })}>
            {STAGES.map((stage) => <option key={stage}>{stage}</option>)}
          </select>
        </label>
        <label className="field-labeled">Partners (Partner note names, comma-separated)
          <input value={draft.partner} onChange={(event) => setDraft({ ...draft, partner: event.target.value })} />
        </label>
        <label className="field-labeled">Billing profile
          <select value={draft.billing_profile} onChange={(event) => setDraft({ ...draft, billing_profile: event.target.value })}>
            <option value="">—</option>
            {analysis.customer.accounts.map((account) => (
              <option key={account.name} value={account.name}>{account.display_name} ({account.name})</option>
            ))}
          </select>
        </label>
      </div>
      <h4>Consumption plan</h4>
      <div className="azure-cost-form-row">
        <label className="field-labeled">Starts
          <input type="month" value={draft.start} onChange={(event) => regenerate({ start: event.target.value })} />
        </label>
        <label className="field-labeled">Steady monthly
          <input type="number" step="1000" value={draft.steady} onChange={(event) => regenerate({ steady: Number(event.target.value) })} />
        </label>
        <label className="field-labeled">Ramp months
          <input type="number" min="0" max="24" value={draft.ramp} onChange={(event) => regenerate({ ramp: Number(event.target.value) })} />
        </label>
      </div>
      <div className="azure-cost-plan-grid">
        {draft.plan.map((row, index) => (
          <label key={row.month} className="field-labeled">{formatMonth(row.month, true)}
            <input type="number" step="1000" value={row.usd}
                   onChange={(event) => setDraft({ ...draft, plan: draft.plan.map((cell, cellIndex) =>
                     cellIndex === index ? { ...cell, usd: Number(event.target.value) } : cell) })} />
          </label>
        ))}
      </div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-toolbar">
        <button type="button" className="btn" onClick={() => onDone(false)}>Cancel</button>
        <button type="button" className="btn" onClick={save} disabled={saving || (!draft.id && !draft.title.trim())}>
          {saving ? 'Saving…' : draft.id ? 'Save to the note' : 'Create the note'}
        </button>
      </div>
    </section>
  );
}

/** The link picker's options: Customers, then Partners, each with its affiliates
 *  indented under it at any depth. */
export function HubOptions({ hubs }: { hubs: EntityCustomer[] }) {
  const groups: [string, EntityCustomer[]][] = [
    ['Customers', hubs.filter((hub) => (hub.kind ?? 'customer') === 'customer')],
    ['Partners', hubs.filter((hub) => hub.kind === 'partner')]];
  return (
    <>
      {groups.filter(([, members]) => members.length).map(([label, members]) => (
        <optgroup key={label} label={label}>
          {flattenHubs(members).map(({ hub, depth, parent }) => (
            <option key={hub.stem} value={hub.stem}>
              {depth ? `${'   '.repeat(depth)}↳ ${hub.name} (affiliate of ${parent?.name})` : hub.name}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

function LinkCustomer({ analysis, onLinked }: { analysis: Analysis; onLinked: () => void }) {
  const [customers, setCustomers] = useState<EntityCustomer[]>([]);
  const [chosen, setChosen] = useState('');
  const [newAffiliate, setNewAffiliate] = useState(analysis.customer.name);
  const [error, setError] = useState<string | null>(null);
  const parentNote = analysis.group.parent?.entity_customer ?? null;
  useEffect(() => {
    fetchEntityCustomers().then((result) => setCustomers(result.customers), (failure) => setError(errorText(failure)));
  }, []);

  function link(stem: string) {
    const customer = analysis.customer;
    saveCustomer(customer.id, { name: customer.name, accounts: customer.accounts.map((account) => account.name),
      commitment: customer.commitment, entity_customer: stem }).then(onLinked, (failure) => setError(errorText(failure)));
  }

  function createAndLink() {
    if (!parentNote) return;
    setError(null);
    createAffiliateNote(parentNote, newAffiliate.trim()).then((created) => link(created.stem),
      (failure) => setError(errorText(failure)));
  }

  const parentHub = parentNote ? findHub(customers, parentNote) : undefined;
  return (
    <section className="card azure-cost-card">
      <h3>Link to the Customer note</h3>
      <p className="text-muted azure-cost-note">
        The pipeline is this customer's Opportunity notes in the vault. Pick the Customer note — or, for an affiliate,
        its affiliate note — they sit under; the Azure name often differs from it.
      </p>
      <div className="azure-cost-toolbar">
        <select value={chosen} onChange={(event) => setChosen(event.target.value)} className="azure-cost-picker">
          <option value="">Choose a Customer, Partner or affiliate note…</option>
          <HubOptions hubs={customers} />
        </select>
        <button type="button" className="btn" onClick={() => link(chosen)} disabled={!chosen}>Link</button>
      </div>
      {analysis.group.parent ? (
        parentNote ? (
          <>
            <p className="text-muted azure-cost-note">
              No affiliate note for it under {parentHub?.name ?? parentNote}? Create one — the Entities plugin writes it.
            </p>
            <div className="azure-cost-toolbar">
              <input value={newAffiliate} onChange={(event) => setNewAffiliate(event.target.value)} />
              <button type="button" className="btn" onClick={createAndLink} disabled={!newAffiliate.trim()}>
                Create the affiliate note and link
              </button>
            </div>
          </>
        ) : (
          <p className="text-muted azure-cost-note">
            Link {analysis.group.parent.name} to its Customer note first; then an affiliate note can be created here.
          </p>
        )
      ) : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
    </section>
  );
}

export function PipelineTab({ analysis, onChanged }: { analysis: Analysis; onChanged: () => void }) {
  const pipeline = analysis.pipeline;
  const currency = analysis.currency;
  const [editing, setEditing] = useState<Draft | null>(null);
  const [owners, setOwners] = useState<{ stem: string; name: string }[]>([]);
  const horizon = `${new Date().getFullYear() + 1}-12`;
  const linked = analysis.customer.entity_customer;

  useEffect(() => {
    if (!linked) return;
    fetchEntityCustomers().then((result) => {
      const customer = findHub(result.customers, linked);
      // Opportunities can sit under the linked note or any of its affiliates, at any depth.
      setOwners(customer ? flattenHubs([customer]).map(({ hub, depth }) =>
        ({ stem: hub.stem, name: depth ? `${hub.name} (affiliate)` : hub.name }))
        : [{ stem: linked, name: linked }]);
    }, () => setOwners([{ stem: linked, name: linked }]));
  }, [linked]);

  const months = useMemo(() => [...new Set(pipeline.opportunities.flatMap((o) => o.plan.map((row) => row.month)))].sort(),
    [pipeline.opportunities]);

  if (!pipeline.available) return <p className="empty-state">{pipeline.reason}</p>;
  if (!linked) return <LinkCustomer analysis={analysis} onLinked={onChanged} />;
  if (editing) {
    return <Editor analysis={analysis} owners={owners} initial={editing}
                   onDone={(saved) => { setEditing(null); if (saved) onChanged(); }} />;
  }

  const counted = pipeline.opportunities.filter((o) => o.status === 'Open' || o.status === 'Won');
  return (
    <>
      <section className="card azure-cost-card">
        <div className="azure-cost-card-head">
          <h3>Opportunities</h3>
          <button type="button" className="btn" onClick={() => setEditing(draftOf(null, owners[0]?.stem ?? linked, horizon))}>
            New opportunity
          </button>
        </div>
        {pipeline.opportunities.length === 0 ? (
          <p className="text-muted">No Opportunity notes under this customer yet.</p>
        ) : (
          <table className="azure-cost-table">
            <thead><tr><th>Opportunity</th><th>Under</th><th>Status</th><th>Stage</th><th>Partner</th>
              <th>Starts</th><th>Steady monthly</th><th>Planned, next 12 months</th><th /></tr></thead>
            <tbody>
              {pipeline.opportunities.map((opportunity) => {
                const thisMonth = new Date().toISOString().slice(0, 7);
                const next12 = opportunity.plan.filter((row) => row.month >= thisMonth && row.month <= addMonths(thisMonth, 11))
                  .reduce((sum, row) => sum + row.usd, 0);
                return (
                  <tr key={opportunity.id}>
                    <td>{opportunity.title}</td>
                    <td className="text-muted">{opportunity.affiliate ?? opportunity.customer}</td>
                    <td>{opportunity.status}</td>
                    <td>{opportunity.stage}</td>
                    <td>{opportunity.partner?.length ? opportunity.partner.join(', ') : '—'}</td>
                    <td>{opportunity.consumption_start ? formatMonth(opportunity.consumption_start) : '—'}</td>
                    <td>{opportunity.expected_monthly_usd ? formatMoney(Number(opportunity.expected_monthly_usd), currency) : '—'}</td>
                    <td>{next12 ? formatMoney(next12, currency) : '—'}</td>
                    <td><button type="button" className="btn" onClick={() => setEditing(draftOf(opportunity, linked, horizon))}>Plan</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="text-muted azure-cost-note">Open and Won opportunities count toward the forecast and the projected MACC consumed.</p>
      </section>
      {counted.length && months.length ? (
        <section className="card azure-cost-card">
          <h3>Expected consumption from the pipeline</h3>
          <SeriesChart label="Pipeline by month" currency={currency} height={300}
                       categories={months} categoryLabel={(m) => formatMonth(m, true)}
                       series={counted.map((opportunity, index) => ({ name: opportunity.title, stack: 'pipeline', color: index,
                         data: months.map((month) => opportunity.plan.find((row) => row.month === month)?.usd ?? 0) }))} />
        </section>
      ) : null}
    </>
  );
}
