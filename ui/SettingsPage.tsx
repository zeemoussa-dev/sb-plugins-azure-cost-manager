import { useEffect, useMemo, useState } from 'react';
import { fetchBillingAccounts, saveTracked, type BillingAccount } from './client';
import { agreementLabel, errorText } from './format';

/** Which billing accounts to follow, out of those the operator's own `az login`
 *  can see. Azure's account names often differ from the Customer note's name;
 *  linking the two is Phase 2. */
export function SettingsPage() {
  const [accounts, setAccounts] = useState<BillingAccount[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBillingAccounts().then((visible) => {
      setAccounts(visible);
      setChosen(new Set(visible.filter((account) => account.tracked).map((account) => account.name)));
    }, (failure) => setError(errorText(failure)));
  }, []);

  const shown = useMemo(() => (accounts ?? []).filter((account) =>
    `${account.display_name} ${account.name}`.toLowerCase().includes(filter.toLowerCase())), [accounts, filter]);

  function toggle(name: string) {
    setChosen((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
    setMessage(null);
  }

  function save() {
    setSaving(true);
    setError(null);
    saveTracked([...chosen]).then((tracked) => {
      setSaving(false);
      setMessage(`Tracking ${tracked.length} billing account${tracked.length === 1 ? '' : 's'}.`);
    }, (failure) => {
      setSaving(false);
      setError(errorText(failure));
    });
  }

  return (
    <div className="azure-cost-settings">
      <h2>Azure Cost Manager</h2>
      <p className="text-muted">
        Billing accounts visible to this machine's <code>az login</code>. Tick the customers to follow;
        their consumption is read from Azure Cost Management and shown on the Azure Cost page.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {accounts === null && !error ? <p className="text-muted">Asking Azure for billing accounts…</p> : null}
      {accounts && accounts.length === 0 ? (
        <p className="empty-state">This sign-in cannot see any billing accounts. Billing Reader on the account is needed.</p>
      ) : null}
      {accounts && accounts.length > 0 ? (
        <>
          <input type="search" placeholder="Filter accounts" value={filter}
                 onChange={(event) => setFilter(event.target.value)} className="azure-cost-filter" />
          <table className="azure-cost-table">
            <thead><tr><th /><th>Billing account</th><th>Agreement</th><th>Id</th></tr></thead>
            <tbody>
              {shown.map((account) => (
                <tr key={account.name} onClick={() => toggle(account.name)} className="azure-cost-clickable">
                  <td><input type="checkbox" checked={chosen.has(account.name)} readOnly aria-label={account.display_name} /></td>
                  <td>{account.display_name}</td>
                  <td><span className="badge">{agreementLabel(account.agreement_type)}</span></td>
                  <td className="text-muted azure-cost-id">{account.name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="azure-cost-toolbar">
            <button type="button" className="btn" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : `Track ${chosen.size} account${chosen.size === 1 ? '' : 's'}`}
            </button>
            {message ? <span className="text-muted">{message}</span> : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
