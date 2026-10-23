import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import {
  dataExportPath, deleteCustomer, fetchBillingAccounts, importData, fetchCommitmentTypes, fetchCustomers, fetchEntityCustomers, fetchUnassigned,
  findHub, saveCustomer, type BillingAccount, type Commitment, type Customer, type EntityCustomer, type UnassignedGroup,
} from './client';
import { agreementLabel, errorText, formatMoney, formatMonth, grouped } from './format';
import { usePluginReturn } from '../../pluginHost/breadcrumbs';
import { useUrlState } from '../../pluginHost/state';
import { PLUGIN_ID } from './ReportsHome';
import { HubOptions } from './PipelineTab';
import { SolutionPlaysSettingsCard } from './SolutionPlays';
import { SolutionCatalogCard } from './Solutions';
import { SyncControl } from './SyncControl';

const SHOWN_WHILE_SEARCHING = 60;

// One section at a time, picked in a side panel as on the Vault's settings
// (operator, 2026-10-21: "the Settings page grew too much").
const SECTIONS = ['customers', 'unassigned', 'plays', 'patterns', 'sync', 'data'] as const;
type Section = typeof SECTIONS[number];
const SECTION_NAV: { id: Section; label: string; icon: string }[] = [
  { id: 'customers', label: 'Customers', icon: 'groups' },
  { id: 'unassigned', label: 'Enrollments in no customer', icon: 'inventory_2' },
  { id: 'plays', label: 'Solution plays', icon: 'category' },
  { id: 'patterns', label: 'Solution patterns', icon: 'lightbulb' },
  { id: 'sync', label: 'Sync', icon: 'sync' },
  { id: 'data', label: 'Move to another machine', icon: 'swap_horiz' },
];

/** Export this plugin's data, or bring in another machine's, so a new machine needs
 *  no sync from scratch (operator, 2026-10-23). */
function DataTransfer({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<'idle' | 'importing'>('idle');
  const [result, setResult] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  function bringIn() {
    if (!file) return;
    setState('importing'); setProblem(null); setResult(null);
    importData(file).then((found) => {
      setResult(`Imported ${found.customers} customer(s) and ${found.enrollments} enrollment(s)' synced data `
        + `(${found.files} file(s)).`);
      setFile(null); setConfirmed(false); onImported();
    }, (failure) => setProblem(errorText(failure))).finally(() => setState('idle'));
  }
  return (
    <section className="card azure-cost-card">
      <h3>Move to another machine</h3>
      <p className="text-muted azure-cost-note">
        The export holds this plugin's data: customers and their enrollments, every synced month, FinOps prices,
        solution plays, Marketplace exclusions and the baseline and quota. Import it on the other machine and it needs
        no sync from scratch -- only the delta since the export. MACCs kept on Customer notes move with the vault.
      </p>
      <div className="azure-cost-toolbar">
        <a className="btn" href={apiUrl(dataExportPath())}>Export data</a>
      </div>
      <h4>Import</h4>
      <div className="azure-cost-toolbar">
        <input type="file" accept=".zip" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setResult(null); }} />
        <label className="azure-cost-check">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          Replace this machine's Azure Cost data with the export
        </label>
        <button type="button" className="btn" disabled={!file || !confirmed || state === 'importing'} onClick={bringIn}>
          {state === 'importing' ? 'Importing…' : 'Import'}
        </button>
      </div>
      {problem ? <div className="azure-cost-error">{problem}</div> : null}
      {result ? <p className="azure-cost-note">{result}</p> : null}
    </section>
  );
}
const ACCOUNT_RETRY_SECONDS = [3, 10, 30, 60];

interface Draft {
  id: string | null;
  name: string;
  accounts: string[];
  entity_customer: string;
  parent: string;
  budget_monthly: string;
  commitment: {
    type: string; amount: string; currency: string; start: string; end: string; note: string;
    include_marketplace: boolean; subtract_credits: boolean; affiliates: 'roll up' | 'own';
  };
}

function draftOf(customer: Customer | null): Draft {
  const commitment: Partial<Commitment> = customer?.commitment ?? {};
  return {
    id: customer?.id ?? null,
    name: customer?.name ?? '',
    accounts: customer?.accounts.map((account) => account.name) ?? [],
    entity_customer: customer?.entity_customer ?? '',
    parent: customer?.parent ?? '',
    budget_monthly: customer?.budget_monthly != null ? String(customer.budget_monthly) : '',
    commitment: {
      type: commitment.type ?? 'MACC', amount: commitment.amount != null ? String(commitment.amount) : '',
      currency: commitment.currency ?? 'USD', start: commitment.start ?? '', end: commitment.end ?? '',
      note: commitment.note ?? '', include_marketplace: commitment.include_marketplace ?? true,
      subtract_credits: commitment.subtract_credits ?? true,
      affiliates: commitment.affiliates === 'own' ? 'own' : 'roll up',
    },
  };
}

function CustomerEditor({ draft, accounts, types, entityCustomers, parents, onSaved, onCancel, commitmentsOnNotes, commitmentProblem }: {
  draft: Draft; accounts: BillingAccount[]; types: string[]; entityCustomers: EntityCustomer[] | null;
  parents: Customer[]; commitmentsOnNotes: boolean; commitmentProblem: string | null;
  onSaved: () => void; onCancel: () => void;
}) {
  const [value, setValue] = useState<Draft>(draft);
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const byName = useMemo(() => new Map(accounts.map((account) => [account.name, account])), [accounts]);
  const chosenKeys = new Set(value.accounts.map((name) => byName.get(name)?.group_key).filter(Boolean));

  const shown = useMemo(() => {
    const query = search.trim().toLowerCase();
    const chosen = accounts.filter((account) => value.accounts.includes(account.name));
    const related = accounts.filter((account) => !value.accounts.includes(account.name)
      && chosenKeys.has(account.group_key));
    const matching = query
      ? accounts.filter((account) => !value.accounts.includes(account.name) && !chosenKeys.has(account.group_key)
        && `${account.display_name} ${account.name}`.toLowerCase().includes(query)).slice(0, SHOWN_WHILE_SEARCHING)
      : [];
    return [...chosen, ...related, ...matching];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accounts, search, value.accounts]);

  function toggle(account: BillingAccount) {
    setValue((current) => {
      const chosen = current.accounts.includes(account.name)
        ? current.accounts.filter((name) => name !== account.name)
        : [...current.accounts, account.name];
      const name = current.name || (chosen.length ? account.display_name.split(/-\d{5,}-/)[0] : '');
      return { ...current, accounts: chosen, name };
    });
  }

  function fillTermFromEnrollments() {
    const chosen = value.accounts.map((name) => byName.get(name)).filter((account): account is BillingAccount => !!account);
    const starts = chosen.map((account) => account.term_start).filter((day): day is string => !!day).sort();
    const ends = chosen.map((account) => account.term_end).filter((day): day is string => !!day).sort();
    setValue((current) => ({ ...current, commitment: { ...current.commitment,
      start: starts[0] ?? current.commitment.start, end: ends[ends.length - 1] ?? current.commitment.end } }));
  }

  function setCommitment(field: keyof Draft['commitment'], fieldValue: string | boolean) {
    setValue((current) => ({ ...current, commitment: { ...current.commitment, [field]: fieldValue } }));
  }

  function save() {
    setSaving(true);
    setError(null);
    const commitment = value.commitment.amount.trim()
      ? { ...value.commitment, amount: Number(value.commitment.amount) } : null;
    saveCustomer(value.id, { name: value.name, accounts: value.accounts, commitment,
      entity_customer: value.entity_customer || null, parent: value.parent || null,
      budget_monthly: value.budget_monthly ? Number(value.budget_monthly) : null }).then(() => {
      setSaving(false);
      onSaved();
    }, (failure) => {
      setSaving(false);
      setError(errorText(failure));
    });
  }

  return (
    <section className="card azure-cost-card azure-cost-editor">
      <h3>{value.id ? `Edit ${draft.name}` : 'New customer'}</h3>
      <label className="field-labeled">Customer name
        <input value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} />
      </label>

      <h4>Enrollments</h4>
      <p className="text-muted azure-cost-note">
        Pick every billing account that is this customer: renewals and linked enrollments read as one.
        Once one is picked, enrollments that look related are listed under it.
      </p>
      <input type="search" placeholder={`Search ${accounts.length} billing accounts by name or number`} value={search}
             onChange={(event) => setSearch(event.target.value)} className="azure-cost-filter" />
      <table className="azure-cost-table">
        <thead><tr><th /><th>Billing account</th><th>Agreement</th><th>Term</th><th>Id</th><th /></tr></thead>
        <tbody>
          {shown.map((account) => {
            const chosen = value.accounts.includes(account.name);
            const related = !chosen && chosenKeys.has(account.group_key);
            const elsewhere = account.customer && account.customer !== value.id ? account.customer : null;
            return (
              <tr key={account.name} onClick={() => toggle(account)} className="azure-cost-clickable">
                <td><input type="checkbox" checked={chosen} readOnly aria-label={account.display_name} /></td>
                <td>{account.display_name}</td>
                <td><span className="badge">{agreementLabel(account.agreement_type)}</span></td>
                <td className="text-muted">{account.term_start ?? '?'} → {account.term_end ?? '?'}</td>
                <td className="text-muted azure-cost-id">{account.name}</td>
                <td>
                  {related ? <span className="azure-cost-anomaly new">related</span> : null}
                  {elsewhere ? <span className="text-muted"> in {elsewhere}</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h4>Group</h4>
      <p className="text-muted azure-cost-note">
        An affiliate's MACC is carved out of its group's: every dollar it consumes counts against both.
      </p>
      <select value={value.parent} onChange={(event) => setValue({ ...value, parent: event.target.value })}
              className="azure-cost-picker">
        <option value="">Not part of a group</option>
        {parents.map((parent) => <option key={parent.id} value={parent.id}>Affiliate of {parent.name}</option>)}
      </select>

      <h4>{value.parent
        ? `Signed MACC — carved out of ${parents.find((parent) => parent.id === value.parent)?.name ?? 'the group'}'s`
        : 'Signed value'}</h4>
      <p className="text-muted azure-cost-note">
        What the customer committed to over the term. Azure does not report it for indirect agreements.{' '}
        {commitmentsOnNotes && value.entity_customer
          ? <>Kept on the note <strong>{(entityCustomers ? findHub(entityCustomers, value.entity_customer)?.name : null) ?? value.entity_customer}</strong> in the vault, as its <code>macc_</code> properties: you can edit it there in Obsidian too.</>
          : commitmentsOnNotes
            ? 'Kept in these settings until the customer is linked to its Customer note below; it then moves to the note.'
            : ''}
      </p>
      {commitmentProblem ? <div className="azure-cost-error">{commitmentProblem}</div> : null}
      <div className="azure-cost-form-row">
        <label className="field-labeled">Type
          <select value={value.commitment.type} onChange={(event) => setCommitment('type', event.target.value)}>
            {types.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label className="field-labeled">Amount
          <input type="number" min="0" step="1000" value={value.commitment.amount}
                 onChange={(event) => setCommitment('amount', event.target.value)} />
        </label>
        <label className="field-labeled">Currency
          <input value={value.commitment.currency} maxLength={3}
                 onChange={(event) => setCommitment('currency', event.target.value)} />
        </label>
        <label className="field-labeled">Term start
          <input type="date" value={value.commitment.start} onChange={(event) => setCommitment('start', event.target.value)} />
        </label>
        <label className="field-labeled">Term end
          <input type="date" value={value.commitment.end} onChange={(event) => setCommitment('end', event.target.value)} />
        </label>
      </div>
      <button type="button" className="btn azure-cost-link-button" onClick={fillTermFromEnrollments}
              disabled={!value.accounts.length}>Use the enrollments' term</button>
      <label className="field-labeled">Note
        <input value={value.commitment.note} onChange={(event) => setCommitment('note', event.target.value)}
               placeholder="e.g. MACC signed with the 2024 renewal" />
      </label>
      <p className="text-muted azure-cost-note">
        Usage and all Marketplace count against it, less credits. An offer marked as not eligible on the
        Marketplace report is left out.
      </p>
      {value.parent ? null : (
        <label className="field-labeled">Affiliates
          <select value={value.commitment.affiliates}
                  onChange={(event) => setCommitment('affiliates', event.target.value)}>
            <option value="roll up">Roll up — they sign no MACC; their consumption counts toward this one</option>
            <option value="own">Own — each signed its own; only this customer's enrollments count toward this one</option>
          </select>
        </label>
      )}

      <h4>Monthly budget (FinOps)</h4>
      <p className="text-muted azure-cost-note">
        Leave empty to use the signed value spread evenly over its term; enter an amount to override it.
      </p>
      <label className="field-labeled">Monthly budget
        <input type="number" min="0" step="1000" value={value.budget_monthly} placeholder="From the MACC"
               onChange={(event) => setValue({ ...value, budget_monthly: event.target.value })} />
      </label>

      <h4>Customer or Partner note</h4>
      <p className="text-muted azure-cost-note">
        The note in the vault -- a Customer, a Partner, or one of their affiliates -- whose Opportunities (its affiliates'
        included) are this customer's pipeline, and which keeps its signed value.
      </p>
      {entityCustomers === null ? (
        <p className="text-muted azure-cost-note">The Entities plugin (1.1 or later) is needed to link a note.</p>
      ) : (
        <select value={value.entity_customer} onChange={(event) => setValue({ ...value, entity_customer: event.target.value })}
                className="azure-cost-picker">
          <option value="">Not linked</option>
          <HubOptions hubs={entityCustomers} />
        </select>
      )}

      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-toolbar">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save customer'}</button>
      </div>
    </section>
  );
}

/** Every enrollment this sign-in sees that belongs to no customer, grouped the
 *  way the editor suggests, biggest spend first; one click starts a customer
 *  from a group (operator, 2026-10-17). */
function UnassignedEnrollments({ version, onCreate }: {
  version: unknown; onCreate: (group: UnassignedGroup) => void;
}) {
  const [groups, setGroups] = useState<UnassignedGroup[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    fetchUnassigned().then((listed) => { setGroups(listed); setProblem(null); },
      (failure) => setProblem(errorText(failure)));
  }, [version]);

  if (problem) return <div className="azure-cost-error">Enrollments in no customer could not be loaded: {problem}</div>;
  if (!groups) return null;
  const needle = search.trim().toLowerCase();
  const shown = groups.filter((group) => !needle || group.accounts.some((account) =>
    `${account.display_name} ${account.name}`.toLowerCase().includes(needle)));
  const enrollments = groups.reduce((sum, group) => sum + group.accounts.length, 0);
  return (
    <section className="card azure-cost-card">
      <div className="azure-cost-card-head">
        <h3>Enrollments in no customer</h3>
        <input type="search" placeholder="Search by name or number" value={search}
               onChange={(event) => setSearch(event.target.value)} aria-label="Search enrollments in no customer" />
      </div>
      <p className="text-muted azure-cost-note">
        {enrollments} enrollment{enrollments === 1 ? '' : 's'} in {groups.length} group{groups.length === 1 ? '' : 's'},
        grouped like the editor's suggestions (a renewal, or linked under one parent), the largest spend first. Spend comes
        from <strong>Sync all billing profiles</strong> below; a group with no spend shown has not been synced that way.
      </p>
      {groups.length === 0 ? <p className="empty-state">Every enrollment belongs to a customer.</p> : (
        <table className="azure-cost-table">
          <thead><tr><th>Group</th><th>Enrollments</th>
            <th>{groups[0] ? formatMonth(groups[0].last_month_label) : 'Last month'}</th><th>Last 12 months</th><th /></tr></thead>
          <tbody>
            {shown.map((group) => (
              <tr key={group.key}>
                <td>{group.name}
                  <div className="text-muted azure-cost-row-detail">
                    {group.accounts.map((account) => `${account.display_name} (${account.name}${account.agreement_type ? `, ${agreementLabel(account.agreement_type)}` : ''})`).join(' · ')}
                  </div></td>
                <td>{group.accounts.length}</td>
                <td>{group.synced ? formatMoney(group.last_month, 'USD') : <span className="text-muted">not synced</span>}</td>
                <td>{group.synced ? formatMoney(group.last_twelve_months, 'USD') : '—'}</td>
                <td><button type="button" className="btn" onClick={() => onCreate(group)}>Create customer</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** Customers -- groups of enrollments with what each signed -- and the sync
 *  that brings their consumption into local data. */
export function SettingsPage() {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [accounts, setAccounts] = useState<BillingAccount[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [entityCustomers, setEntityCustomers] = useState<EntityCustomer[] | null>(null);
  const [commitmentsOnNotes, setCommitmentsOnNotes] = useState(false);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [section, setSection] = useUrlState<Section>('section', 'customers', { valid: SECTIONS });
  const navigate = useNavigate();
  const back = usePluginReturn(PLUGIN_ID);
  // A customer opened from a report is edited for that report: done, it goes back there.
  const openedFromReport = Boolean(back && params.get('customer'));
  const finish = (saved: boolean) => {
    if (back && openedFromReport) { navigate(back.to); return; }
    setEditing(null);
    if (saved) load();
  };

  const [accountsProblem, setAccountsProblem] = useState<string | null>(null);
  const retry = useRef<number | undefined>(undefined);

  // While the backend restarts -- a plugin install, a framework change -- the
  // plugin's routes answer 404 for a few seconds. One failed fetch used to leave
  // the billing accounts empty until a full reload, so nothing could be linked
  // (operator, 2026-10-17); it now tries again, a little later each time.
  const loadAccounts = useCallback((attempt = 0) => {
    window.clearTimeout(retry.current);
    fetchBillingAccounts().then((listed) => { setAccounts(listed); setAccountsProblem(null); }, (failure) => {
      const delay = ACCOUNT_RETRY_SECONDS[attempt];
      setAccountsProblem(`Billing accounts could not be loaded: ${errorText(failure)}.`
        + (delay ? ` Trying again in ${delay} seconds.` : ''));
      if (delay) retry.current = window.setTimeout(() => loadAccounts(attempt + 1), delay * 1000);
    });
  }, []);

  useEffect(() => () => window.clearTimeout(retry.current), []);

  const load = useCallback(() => {
    fetchCustomers().then((listed) => {
      setCustomers(listed);
      setError(null);
      const wanted = params.get('customer');
      const match = wanted ? listed.find((customer) => customer.id === wanted) : null;
      if (match) setEditing((current) => current ?? draftOf(match));
    }, (failure) => setError(errorText(failure)));
    loadAccounts();
  }, [params, loadAccounts]);

  useEffect(() => {
    load();
    fetchCommitmentTypes().then(setTypes, () => setTypes(['MACC', 'EA commitment', 'Azure Prepayment', 'Other']));
    fetchEntityCustomers().then((result) => {
      setEntityCustomers(result.available ? result.customers : null);
      setCommitmentsOnNotes(Boolean(result.commitments_on_notes));
    },
      () => setEntityCustomers(null));
  }, [load]);

  function remove(customer: Customer) {
    if (!window.confirm(`Remove ${customer.name}? Its synced consumption is dropped from local data too.`)) return;
    deleteCustomer(customer.id).then(load, (failure) => setError(errorText(failure)));
  }

  const syncUrl = apiUrl('/plugins/azure-cost-manager/sync');

  // A customer opened for editing is always shown in its own section.
  const shown: Section = editing ? 'customers' : section;
  const parentOf = (customer: Customer) => customers?.find((other) => other.id === customer.parent) ?? null;

  return (
    <div className="azure-cost-settings">
      <h2>Azure Customer 360</h2>
      <div className="vault-settings-layout">
        <nav className="vault-settings-nav" aria-label="Azure Customer 360 settings">
          {SECTION_NAV.map((item) => (
            <button key={item.id} type="button"
                    className={`vault-settings-nav-item artifacts-nav-item${shown === item.id ? ' vault-settings-nav-item--active' : ''}`}
                    aria-current={shown === item.id ? 'page' : undefined}
                    onClick={() => { setEditing(null); setSection(item.id); }}>
              <span className="material-symbols-outlined" aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="vault-settings-content">
      {accountsProblem ? (
        <div className="azure-cost-error">{accountsProblem}{' '}
          <button type="button" className="btn" onClick={() => loadAccounts()}>Try again</button>
        </div>
      ) : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}

      {shown !== 'customers' ? null : editing ? (
        <CustomerEditor draft={editing} accounts={accounts} types={types} entityCustomers={entityCustomers}
                        parents={(customers ?? []).filter((customer) => !customer.parent && customer.id !== editing.id)}
                        commitmentsOnNotes={commitmentsOnNotes}
                        commitmentProblem={customers?.find((customer) => customer.id === editing.id)?.commitment_problem ?? null}
                        onSaved={() => finish(true)} onCancel={() => finish(false)} />
      ) : (
        <section className="card azure-cost-card">
          <div className="azure-cost-card-head">
            <h3>Customers</h3>
            <button type="button" className="btn" onClick={() => setEditing(draftOf(null))}>Add customer</button>
          </div>
          {customers && customers.length === 0 ? <p className="empty-state">No customers yet.</p> : null}
          {customers && customers.length > 0 ? (
            <table className="azure-cost-table">
              <thead><tr><th>Customer</th><th>Enrollments</th><th>Signed value</th><th>Term</th><th>Synced</th><th /></tr></thead>
              <tbody>
                {grouped(customers).map((customer) => (
                  <tr key={customer.id}>
                    <td>{customer.parent ? <span className="azure-cost-affiliate-name">↳ {customer.name}</span> : customer.name}
                      {customer.affiliates?.length ? <span className="text-muted"> · group of {customer.affiliates.length + 1}</span> : null}</td>
                    <td title={customer.accounts.map((account) => `${account.display_name} (${account.name})`).join('\n')}>
                      {customer.accounts.length}
                    </td>
                    <td>{customer.commitment
                      ? `${formatMoney(customer.commitment.amount, customer.commitment.currency, true)} ${customer.commitment.type}`
                      : parentOf(customer)?.commitment && parentOf(customer)?.commitment?.affiliates !== 'own'
                        ? <span className="text-muted">in {parentOf(customer)!.name}'s MACC</span>
                        : <span className="text-muted">not entered</span>}
                      {customer.commitment && customer.commitment_source === 'note' ? <span className="text-muted"> · on its Customer note</span> : null}
                      {customer.commitment_problem ? <div className="azure-cost-anomaly spike">{customer.commitment_problem}</div> : null}</td>
                    <td className="text-muted">{customer.commitment ? `${customer.commitment.start} → ${customer.commitment.end}` : ''}</td>
                    <td className="text-muted">{customer.synced_at ? new Date(customer.synced_at).toLocaleDateString() : 'never'}</td>
                    <td className="azure-cost-row-actions">
                      <button type="button" className="btn" onClick={() => setEditing(draftOf(customer))}>Edit</button>
                      <button type="button" className="btn" onClick={() => remove(customer)}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </section>
      )}

      {shown === 'unassigned' ? (
        <UnassignedEnrollments version={customers}
                               onCreate={(group) => setEditing({ ...draftOf(null), name: group.name,
                                                                 accounts: group.accounts.map((account) => account.name) })} />
      ) : null}

      {shown === 'plays' ? <SolutionPlaysSettingsCard /> : null}

      {shown === 'patterns' ? <SolutionCatalogCard /> : null}

      {shown === 'data' ? <DataTransfer onImported={load} /> : null}

      {shown === 'sync' ? (
      <section className="card azure-cost-card">
        <h3>Sync</h3>
        <p className="text-muted azure-cost-note">
          Consumption is loaded into local data from each enrollment's term start, a year per query,
          waiting out Azure's throttling. A month Azure has finished settling is never fetched again, so a
          weekly sync only fetches the last few weeks. The first sync of a large customer can take minutes.
        </p>
        <SyncControl onSynced={load} />
        <SyncControl profiles="only" label="Sync all billing profiles" onSynced={load} details={false} />
        <p className="text-muted azure-cost-note">
          Billing profiles that are no customer yet are synced lightly — invoice totals and Marketplace charges — so the
          Marketplace report covers every buyer.
        </p>
        <p className="text-muted azure-cost-note">
          Weekly: create a Hermes cron job that sends <code>POST {syncUrl}?profiles=also</code> (no body) — every customer,
          then every other billing profile. It returns at once; progress shows here and on the Azure Cost page.
        </p>
      </section>
      ) : null}
        </div>
      </div>
    </div>
  );
}
