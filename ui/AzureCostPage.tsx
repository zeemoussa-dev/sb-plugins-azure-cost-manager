import { useCallback, useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';
import { apiUrl } from '../../pluginHost/api';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useRememberedState, useUrlSelection, useUrlState } from '../../pluginHost/state';
import { BreakdownTab } from './BreakdownTab';
import { MarketplaceTab } from './MarketplaceTab';
import {
  exportPath, fetchAnalysis, fetchCustomers, fetchSignIn,
  type Analysis, type Customer, type Measure, type SignInState, type View,
} from './client';
import { ForecastTab } from './ForecastTab';
import { CustomerPortfolio } from './CustomerPortfolio';
import { FinOpsTab } from './FinOpsTab';
import { TagsTab } from './TagsTab';
import { ThisMonthTab } from './ThisMonthTab';
import { errorText } from './format';
import { OverviewTab } from './OverviewTab';
import { PipelineTab } from './PipelineTab';
import { REPORTS, reportLink, reportTitle, settingsLink, type Report } from './ReportsHome';
import { SyncControl } from './SyncControl';

const VIEWS = ['account', 'customer'] as const;

function CustomerView({ customerId, measure, syncedVersion, report, view }: {
  customerId: string; measure: Measure; syncedVersion: number; report: Report; view: View;
}) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [reloads, setReloads] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAnalysis(customerId, measure, view).then((result) => { setAnalysis(result); setError(null); },
      (failure) => setError(errorText(failure)));
  }, [customerId, measure, syncedVersion, reloads, view]);

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
          : report === 'FinOps' ? <FinOpsTab customerId={customerId} syncedVersion={syncedVersion} view={view} />
          : report === 'Tags' ? <TagsTab customerId={customerId} syncedVersion={syncedVersion} view={view} />
          : report === 'This month' ? <ThisMonthTab customerId={customerId} view={view} />
          : nothingBilled ? <p className="empty-state">Nothing was billed on these enrollments in the synced period.</p>
            : report === 'Overview' ? <OverviewTab analysis={analysis} />
              : report === 'Forecast' ? <ForecastTab analysis={analysis} onChanged={reload} />
                : <BreakdownTab analysis={analysis} syncedVersion={syncedVersion} />}
    </div>
  );
}

/** One report: without a customer in the URL it asks for one, with one it shows the report. */
export function AzureCostPage() {
  const location = useLocation();
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  // What is looked at lives in the URL, so a refresh or a shared link lands on it;
  // how it is measured is a preference, remembered per browser (framework API 10).
  const [selected] = useUrlSelection('customer');
  const [report, setReport] = useUrlState<Report>('report', 'Overview', { valid: REPORTS });
  // Who the page is for: the Customer view leaves out the forecast scenarios, on the
  // server, so it can be shown on a shared screen and exported for the customer.
  const [view, setView] = useUrlState<View>('view', 'account', { valid: VIEWS });
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
      <Breadcrumbs items={[
        { label: 'Azure Cost', to: '/azure-cost-manager' },
        { label: reportTitle(report), to: reportLink(report) },
        ...(parent ? [{ label: parent.name, to: reportLink(report, parent.id) }] : []),
        ...(customer ? [{ label: customer.name }] : []),
      ]} />
      <header className="azure-cost-header">
        <h1>{customer ? customer.name : reportTitle(report)}</h1>
        {customer && view === 'customer' ? null : customer ? (
          <Link to={settingsLink({ location, label: customer.name }, customer.id)} className="btn azure-cost-settings-link">
            Edit {customer.name}: MACC, enrollments
          </Link>
        ) : (
          <Link to={settingsLink({ location, label: reportTitle(report) })} className="azure-cost-settings-link">
            Customers and enrollments
          </Link>
        )}
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!customers ? <p className="text-muted">Loading…</p>
        : selected && !customer ? (
          <p className="empty-state">That customer no longer exists. <Link to={reportLink(report)}>Choose another</Link>.</p>
        ) : !customer ? <CustomerPortfolio report={report} />
          : (
            <>
              <div className="azure-cost-toolbar">
                <div className="azure-cost-segmented" role="group" aria-label="View">
                  <button type="button" aria-pressed={view === 'account'} className={view === 'account' ? 'active' : undefined}
                          onClick={() => setView('account')}>My view</button>
                  <button type="button" aria-pressed={view === 'customer'} className={view === 'customer' ? 'active' : undefined}
                          onClick={() => setView('customer')}>Customer view</button>
                </div>
                {view === 'customer' ? (
                  <span className="text-muted azure-cost-note">What {customer.name} sees: everything but the forecast scenarios.</span>
                ) : null}
              </div>
              {view === 'account' ? <SyncControl customerId={customer.id} syncedAt={customer.synced_at} onSynced={onSynced} /> : null}
              <div className="azure-cost-toolbar azure-cost-tabs-row">
                <div className="azure-cost-segmented" role="tablist">
                  {REPORTS.map((name) => (
                    <button key={name} type="button" role="tab" aria-selected={report === name}
                            className={report === name ? 'active' : undefined} onClick={() => setReport(name)}>{name}</button>
                  ))}
                </div>
                <label className="azure-cost-check"
                       title="Marketplace always counts toward the customer's MACC consumed. Core42's revenue is everything except Marketplace bought from other publishers.">
                  Marketplace{' '}
                  <select value={String(measure.marketplace)}
                          onChange={(event) => setMeasure({ ...measure,
                            marketplace: event.target.value === 'core42' ? 'core42' : event.target.value === 'true' })}>
                    <option value="true">All (MACC consumed)</option>
                    <option value="core42">Core42's only (Core42 revenue)</option>
                    <option value="false">None</option>
                  </select>
                </label>
                <label className="azure-cost-check" title="Credits applied to the bill, e.g. a Contract Price Match Credit">
                  <input type="checkbox" checked={measure.credits}
                         onChange={(event) => setMeasure({ ...measure, credits: event.target.checked })} />
                  Subtract credits
                </label>
                <a className="btn" href={apiUrl(exportPath(customer.id, measure, view))}>
                  {view === 'customer' ? 'Export for the customer' : 'Export to Excel'}
                </a>
              </div>
              <CustomerView key={customer.id} customerId={customer.id} measure={measure} syncedVersion={syncedVersion}
                            report={report} view={view} />
            </>
          )}
    </div>
  );
}
