import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import { BreakdownTab } from './BreakdownTab';
import {
  exportPath, fetchAnalysis, fetchCustomers, fetchSignIn,
  type Analysis, type Customer, type Measure, type SignInState,
} from './client';
import { ForecastTab } from './ForecastTab';
import { errorText } from './format';
import { OverviewTab } from './OverviewTab';
import { PipelineTab } from './PipelineTab';
import { SyncControl } from './SyncControl';

const SETTINGS = '/settings/plugins/azure-cost-manager';
const TABS = ['Overview', 'Forecast', 'Pipeline', 'Breakdown'] as const;
type Tab = typeof TABS[number];

function CustomerView({ customerId, measure, syncedVersion, tab }: {
  customerId: string; measure: Measure; syncedVersion: number; tab: Tab;
}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAnalysis(customerId, measure).then((result) => { setAnalysis(result); setError(null); },
      (failure) => setError(errorText(failure)));
  }, [customerId, measure, syncedVersion, reloads]);

  const reload = useCallback(() => setReloads((count) => count + 1), []);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!analysis) return <p className="text-muted">Loading…</p>;

  const accountErrors = Object.entries(analysis.errors);
  const nothingSynced = analysis.months.length === 0;
  const nothingBilled = !nothingSynced && analysis.months.every((month) => !month.actual && !month.amortized);

  return (
    <div className="azure-cost-account">
      <p className="text-muted azure-cost-note">
        {analysis.customer.accounts.length} enrollment{analysis.customer.accounts.length === 1 ? '' : 's'}:{' '}
        {analysis.customer.accounts.map((account) => `${account.display_name} (${account.name})`).join(' · ')}
        {analysis.stale && analysis.synced_at ? ' — data is over a week old' : ''}
      </p>
      {accountErrors.length ? (
        <p className="text-muted azure-cost-note">
          Some months could not be fetched and will be retried on the next sync:{' '}
          {accountErrors.map(([account, errors]) => `${account}: ${Object.keys(errors).join(', ')}`).join('; ')}
        </p>
      ) : null}
      {tab === 'Pipeline' ? <PipelineTab analysis={analysis} onChanged={reload} />
        : nothingSynced ? <p className="empty-state">Nothing synced for this customer yet. Sync it to load its consumption.</p>
          : nothingBilled ? <p className="empty-state">Nothing was billed on these enrollments in the synced period.</p>
            : tab === 'Overview' ? <OverviewTab analysis={analysis} />
              : tab === 'Forecast' ? <ForecastTab analysis={analysis} onChanged={reload} />
                : <BreakdownTab analysis={analysis} syncedVersion={syncedVersion} />}
    </div>
  );
}

export function AzureCostPage() {
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [syncedVersion, setSyncedVersion] = useState(0);
  const [measure, setMeasure] = useState<Measure>({ marketplace: true, credits: true });
  const [tab, setTab] = useState<Tab>('Overview');
  const [error, setError] = useState<string | null>(null);

  const loadCustomers = useCallback(() => {
    fetchCustomers().then((listed) => {
      setCustomers(listed);
      setSelected((current) => current && listed.some((customer) => customer.id === current)
        ? current : listed[0]?.id ?? null);
    }, (failure) => setError(errorText(failure)));
  }, []);

  useEffect(() => {
    fetchSignIn().then(setSignIn, () => setSignIn(null));
    loadCustomers();
  }, [loadCustomers]);

  const onSynced = useCallback(() => {
    loadCustomers();
    setSyncedVersion((version) => version + 1);
  }, [loadCustomers]);

  const customer = customers?.find((candidate) => candidate.id === selected) ?? null;

  return (
    <div className="page azure-cost-page">
      <header className="azure-cost-header">
        <h1>Azure Cost</h1>
        {customers && customers.length > 0 ? (
          <select value={selected ?? ''} onChange={(event) => setSelected(event.target.value)}
                  aria-label="Customer" className="azure-cost-picker">
            {customers.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>{candidate.name}</option>
            ))}
          </select>
        ) : null}
        <Link to={SETTINGS} className="azure-cost-settings-link">Customers</Link>
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {customers && customers.length === 0 ? (
        <p className="empty-state">
          No customers yet. <Link to={SETTINGS}>Add a customer</Link> and pick its enrollments.
        </p>
      ) : null}
      {customer ? (
        <>
          <SyncControl customerId={customer.id} syncedAt={customer.synced_at} onSynced={onSynced} />
          <div className="azure-cost-toolbar azure-cost-tabs-row">
            <div className="azure-cost-segmented" role="tablist">
              {TABS.map((name) => (
                <button key={name} type="button" role="tab" aria-selected={tab === name}
                        className={tab === name ? 'active' : undefined} onClick={() => setTab(name)}>{name}</button>
              ))}
            </div>
            <label className="azure-cost-check" title="Marketplace burns the customer's MACC but does not count toward quota">
              <input type="checkbox" checked={measure.marketplace}
                     onChange={(event) => setMeasure({ ...measure, marketplace: event.target.checked })} />
              Include Marketplace
            </label>
            <label className="azure-cost-check" title="Credits applied to the bill, e.g. a Contract Price Match Credit">
              <input type="checkbox" checked={measure.credits}
                     onChange={(event) => setMeasure({ ...measure, credits: event.target.checked })} />
              Subtract credits
            </label>
            <a className="btn" href={apiUrl(exportPath(customer.id, measure))}>Export to Excel</a>
          </div>
          <CustomerView key={customer.id} customerId={customer.id} measure={measure} syncedVersion={syncedVersion} tab={tab} />
        </>
      ) : null}
    </div>
  );
}
