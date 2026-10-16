import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import {
  deleteCustomer, fetchBillingAccounts, fetchCommitmentTypes, fetchCustomers, saveCustomer,
  type BillingAccount, type Commitment, type Customer,
} from './client';
import { agreementLabel, errorText, formatMoney } from './format';
import { SyncControl } from './SyncControl';

const SHOWN_WHILE_SEARCHING = 60;

interface Draft {
  id: string | null;
  name: string;
  accounts: string[];
  commitment: { type: string; amount: string; currency: string; start: string; end: string; note: string };
}

function draftOf(customer: Customer | null): Draft {
  const commitment: Partial<Commitment> = customer?.commitment ?? {};
  return {
    id: customer?.id ?? null,
    name: customer?.name ?? '',
    accounts: customer?.accounts.map((account) => account.name) ?? [],
    commitment: {
      type: commitment.type ?? 'MACC', amount: commitment.amount != null ? String(commitment.amount) : '',
      currency: commitment.currency ?? 'USD', start: commitment.start ?? '', end: commitment.end ?? '',
      note: commitment.note ?? '',
    },
  };
}

function CustomerEditor({ draft, accounts, types, onSaved, onCancel }: {
  draft: Draft; accounts: BillingAccount[]; types: string[]; onSaved: () => void; onCancel: () => void;
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

  function setCommitment(field: keyof Draft['commitment'], fieldValue: string) {
    setValue((current) => ({ ...current, commitment: { ...current.commitment, [field]: fieldValue } }));
  }

  function save() {
    setSaving(true);
    setError(null);
    const commitment = value.commitment.amount.trim()
      ? { ...value.commitment, amount: Number(value.commitment.amount) } : null;
    saveCustomer(value.id, { name: value.name, accounts: value.accounts, commitment }).then(() => {
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

      <h4>Signed value</h4>
      <p className="text-muted azure-cost-note">
        What the customer committed to over the term. Azure does not report it for indirect agreements.
      </p>
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

      {error ? <div className="azure-cost-error">{error}</div> : null}
      <div className="azure-cost-toolbar">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save customer'}</button>
      </div>
    </section>
  );
}

/** Customers -- groups of enrollments with what each signed -- and the sync
 *  that brings their consumption into local data. */
export function SettingsPage() {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [accounts, setAccounts] = useState<BillingAccount[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();

  const load = useCallback(() => {
    fetchCustomers().then((listed) => {
      setCustomers(listed);
      const wanted = params.get('customer');
      const match = wanted ? listed.find((customer) => customer.id === wanted) : null;
      if (match) setEditing((current) => current ?? draftOf(match));
    }, (failure) => setError(errorText(failure)));
    fetchBillingAccounts().then(setAccounts, (failure) => setError(errorText(failure)));
  }, [params]);

  useEffect(() => {
    load();
    fetchCommitmentTypes().then(setTypes, () => setTypes(['MACC', 'EA commitment', 'Azure Prepayment', 'Other']));
  }, [load]);

  function remove(customer: Customer) {
    if (!window.confirm(`Remove ${customer.name}? Its synced consumption is dropped from local data too.`)) return;
    deleteCustomer(customer.id).then(load, (failure) => setError(errorText(failure)));
  }

  const syncUrl = apiUrl('/plugins/azure-cost-manager/sync');

  return (
    <div className="azure-cost-settings">
      <h2>Azure Cost Manager</h2>
      {error ? <div className="azure-cost-error">{error}</div> : null}

      {editing ? (
        <CustomerEditor draft={editing} accounts={accounts} types={types}
                        onSaved={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />
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
                {customers.map((customer) => (
                  <tr key={customer.id}>
                    <td>{customer.name}</td>
                    <td title={customer.accounts.map((account) => `${account.display_name} (${account.name})`).join('\n')}>
                      {customer.accounts.length}
                    </td>
                    <td>{customer.commitment
                      ? `${formatMoney(customer.commitment.amount, customer.commitment.currency, true)} ${customer.commitment.type}`
                      : <span className="text-muted">not entered</span>}</td>
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

      <section className="card azure-cost-card">
        <h3>Sync</h3>
        <p className="text-muted azure-cost-note">
          Consumption is loaded into local data from each enrollment's term start, a year per query,
          waiting out Azure's throttling. A month Azure has finished settling is never fetched again, so a
          weekly sync only fetches the last few weeks. The first sync of a large customer can take minutes.
        </p>
        <SyncControl onSynced={load} />
        <p className="text-muted azure-cost-note">
          Weekly: create a Hermes cron job that sends <code>POST {syncUrl}</code> (no body). It returns at once;
          progress shows here and on the Azure Cost page.
        </p>
      </section>
    </div>
  );
}
