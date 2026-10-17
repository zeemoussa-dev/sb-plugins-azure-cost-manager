import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import { useRememberedState, useUrlSelection, useUrlState } from '../../pluginHost/state';
import { BreakdownTab } from './BreakdownTab';
import { MarketplaceTab } from './MarketplaceTab';
import {
  exportPath, fetchAnalysis, fetchCustomers, fetchSignIn,
  type Analysis, type Customer, type Measure, type SignInState,
} from './client';
import { ForecastTab } from './ForecastTab';
import { errorText, formatMoney, grouped } from './format';
import { OverviewTab } from './OverviewTab';
import { PipelineTab } from './PipelineTab';
import { REPORTS, reportLink, reportTitle, SETTINGS_PATH, type Report } from './ReportsHome';
import { SyncControl } from './SyncControl';

function CustomerView({ customerId, measure, syncedVersion, report }: {
  customerId: string; measure: Measure; syncedVersion: number; report: Report;
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
        {analysis.group.accounts.length} enrollment{analysis.group.accounts.length === 1 ? '' : 's'}
        {analysis.group.affiliates.length ? ` across ${analysis.customer.name} and ${analysis.group.affiliates.length} affiliate${analysis.group.affiliates.length === 1 ? '' : 's'}` : ''}:{' '}
        {analysis.group.accounts.map((account) => `${account.display_name} (${account.name})`).join(' · ')}
        {analysis.stale && analysis.synced_at ? ' — data is over a week old' : ''}
      </p>
      {accountErrors.length ? (
        <p className="text-muted azure-cost-note">
          Some months could not be fetched and will be retried on the next sync:{' '}
          {accountErrors.map(([account, errors]) => `${account}: ${Object.keys(errors).join(', ')}`).join('; ')}
        </p>
      ) : null}
      {report === 'Pipeline' ? <PipelineTab analysis={analysis} onChanged={reload} />
        : nothingSynced ? <p className="empty-state">Nothing synced for this customer yet. Sync it to load its consumption.</p>
          : report === 'Marketplace' ? <MarketplaceTab customerId={customerId} currency={analysis.currency} syncedVersion={syncedVersion} />
          : nothingBilled ? <p className="empty-state">Nothing was billed on these enrollments in the synced period.</p>
            : report === 'Overview' ? <OverviewTab analysis={analysis} />
              : report === 'Forecast' ? <ForecastTab analysis={analysis} onChanged={reload} />
                : <BreakdownTab analysis={analysis} syncedVersion={syncedVersion} />}
    </div>
  );
}

function syncedText(syncedAt: string | null): string {
  return syncedAt ? new Date(syncedAt).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : 'Not synced';
}

/** Every customer, each group's affiliates under it; a click opens the report for that customer. */
function CustomerChooser({ customers, report }: { customers: Customer[]; report: Report }) {
  const [search, setSearch] = useUrlState<string>('search', '');
  const byId = useMemo(() => new Map(customers.map((customer) => [customer.id, customer])), [customers]);
  const needle = search.trim().toLowerCase();
  // A match keeps its whole group in view, so an affiliate is never shown without its parent.
  const shown = grouped(customers).filter((customer) => {
    if (!needle) return true;
    const group = customer.parent && byId.has(customer.parent) ? byId.get(customer.parent)! : customer;
    return [group, ...customers.filter((member) => member.parent === group.id)]
      .some((member) => member.name.toLowerCase().includes(needle));
  });

  if (customers.length === 0) {
    return <p className="empty-state">No customers yet. <Link to={SETTINGS_PATH}>Add a customer</Link> and pick its enrollments.</p>;
  }
  return (
    <section className="card azure-cost-card">
      <div className="azure-cost-card-head">
        <h3>Choose a customer</h3>
        <input type="search" placeholder="Search customers" value={search}
               onChange={(event) => setSearch(event.target.value)} aria-label="Search customers" />
      </div>
      <table className="azure-cost-table azure-cost-chooser">
        <thead><tr><th>Customer</th><th>Signed MACC</th><th>Enrollments</th><th>Last synced</th></tr></thead>
        <tbody>
          {shown.map((customer) => {
            const isAffiliate = Boolean(customer.parent && byId.has(customer.parent));
            const isGroup = Boolean(customer.affiliates?.length);
            return (
              <tr key={customer.id} className={isAffiliate ? 'azure-cost-chooser-affiliate' : 'azure-cost-chooser-top'}>
                <td>
                  <Link to={reportLink(report, customer.id)}>{isAffiliate ? '↳ ' : ''}{customer.name}</Link>
                  {isGroup ? <span className="text-muted"> · group of {customer.affiliates!.length + 1}</span> : null}
                  {isAffiliate ? <span className="text-muted"> · affiliate</span> : null}
                </td>
                <td>{customer.commitment ? formatMoney(customer.commitment.amount, customer.commitment.currency) : '—'}</td>
                <td>{customer.accounts.length}</td>
                <td className="text-muted">{syncedText(customer.synced_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {shown.length === 0 ? <p className="text-muted">No customer matches “{search}”.</p> : null}
    </section>
  );
}

/** One report: without a customer in the URL it asks for one, with one it shows the report. */
export function AzureCostPage() {
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  // What is looked at lives in the URL, so a refresh or a shared link lands on it;
  // how it is measured is a preference, remembered per browser (framework API 10).
  const [selected] = useUrlSelection('customer');
  const [report, setReport] = useUrlState<Report>('report', 'Overview', { valid: REPORTS });
  const [syncedVersion, setSyncedVersion] = useState(0);
  const [measure, setMeasure] = useRememberedState<Measure>('azure-cost-manager.measure',
    { marketplace: true, credits: true });
  const [error, setError] = useState<string | null>(null);

  const loadCustomers = useCallback(() => {
    fetchCustomers().then(setCustomers, (failure) => setError(errorText(failure)));
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
  const parent = customer?.parent ? customers?.find((candidate) => candidate.id === customer.parent) ?? null : null;

  return (
    <div className="page azure-cost-page">
      <nav className="azure-cost-breadcrumb" aria-label="Breadcrumb">
        <Link to="/azure-cost-manager">Reports</Link>
        <span aria-hidden="true">›</span>
        {customer ? <Link to={reportLink(report)}>{reportTitle(report)}</Link> : <span>{reportTitle(report)}</span>}
        {parent ? <><span aria-hidden="true">›</span><Link to={reportLink(report, parent.id)}>{parent.name}</Link></> : null}
        {customer ? <><span aria-hidden="true">›</span><span>{customer.name}</span></> : null}
      </nav>
      <header className="azure-cost-header">
        <h1>{customer ? customer.name : reportTitle(report)}</h1>
        <Link to={SETTINGS_PATH} className="azure-cost-settings-link">Customers and enrollments</Link>
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!customers ? <p className="text-muted">Loading…</p>
        : selected && !customer ? (
          <p className="empty-state">That customer no longer exists. <Link to={reportLink(report)}>Choose another</Link>.</p>
        ) : !customer ? <CustomerChooser customers={customers} report={report} />
          : (
            <>
              <SyncControl customerId={customer.id} syncedAt={customer.synced_at} onSynced={onSynced} />
              <div className="azure-cost-toolbar azure-cost-tabs-row">
                <div className="azure-cost-segmented" role="tablist">
                  {REPORTS.map((name) => (
                    <button key={name} type="button" role="tab" aria-selected={report === name}
                            className={report === name ? 'active' : undefined} onClick={() => setReport(name)}>{name}</button>
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
              <CustomerView key={customer.id} customerId={customer.id} measure={measure} syncedVersion={syncedVersion} report={report} />
            </>
          )}
    </div>
  );
}
