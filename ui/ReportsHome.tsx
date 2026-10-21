import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router';
import { pluginSettingsLink } from '../../pluginHost/breadcrumbs';
import { fetchCustomers, fetchSignIn, type Customer, type SignInState } from './client';
import { errorText } from './format';

export const REPORT_PATH = '/azure-cost-manager/report';

export const REPORTS = ['Overview', 'This month', 'Forecast', 'Pipeline', 'Marketplace', 'FinOps', 'Tags', 'Breakdown'] as const;
export type Report = typeof REPORTS[number];

const REPORT_SUMMARIES: Record<Report, { title: string; summary: string }> = {
  Overview: { title: 'Consumption overview', summary: 'Signed MACC, MACC consumed, monthly consumption, top services and anomalies.' },
  'This month': { title: 'This month', summary: 'This month so far, day by day: pace against last month and every new service, subscription or resource group -- early signs of an opportunity.' },
  Forecast: { title: 'Forecast', summary: 'Run rate and where consumption lands by the end of the term.' },
  Pipeline: { title: 'Pipeline', summary: 'The customer\'s Opportunities and their effect on consumption.' },
  Marketplace: { title: 'Marketplace', summary: 'The partner solutions one customer bought, and how much of its MACC they consumed.' },
  FinOps: { title: 'FinOps', summary: 'Commitment coverage, steady on-demand spend to commit, purchases, growth and the budget.' },
  Tags: { title: 'Tags', summary: 'Cost by environment, project, application, business unit, owner and cost centre tags.' },
  Breakdown: { title: 'Breakdown', summary: 'Consumption by service, subscription and resource group.' },
};

export function reportTitle(report: Report): string {
  return REPORT_SUMMARIES[report].title;
}

export const PLUGIN_ID = 'azure-cost-manager';

/** Settings, opened on one customer's editor when customerId is given. rom
 *  names the page it was opened from, so the host's trail and Save/Cancel lead
 *  back there; the landing page passes none, as the trail starts with it anyway. */
export function settingsLink(from?: { location: { pathname: string; search: string }; label: string },
                             customerId?: string): string {
  return pluginSettingsLink(PLUGIN_ID, {
    params: customerId ? { customer: customerId } : undefined,
    from: from?.location, fromLabel: from?.label,
  });
}

export function reportLink(report: Report, customerId?: string): string {
  const search = new URLSearchParams({ report });
  if (customerId) search.set('customer', customerId);
  return `${REPORT_PATH}?${search}`;
}

/** The landing page: pick a report first, then the customer it is about. */
export function ReportsHome() {
  const location = useLocation();
  const [signIn, setSignIn] = useState<SignInState | null>(null);
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSignIn().then(setSignIn, () => setSignIn(null));
    fetchCustomers().then(setCustomers, (failure) => setError(errorText(failure)));
  }, []);

  // Links and bookmarks from before the landing page carried ?customer=&tab=.
  const legacy = new URLSearchParams(location.search);
  if (legacy.get('customer')) {
    const tab = legacy.get('tab');
    const report = (REPORTS as readonly string[]).includes(tab ?? '') ? tab as Report : 'Overview';
    return <Navigate to={reportLink(report, legacy.get('customer')!)} replace />;
  }

  return (
    <div className="page azure-cost-page">
      <header className="azure-cost-header">
        <h1>Azure Cost</h1>
        <Link to={settingsLink()} className="azure-cost-settings-link">Customers and enrollments</Link>
      </header>
      {signIn && !signIn.signed_in ? <div className="azure-cost-error">{signIn.message}</div> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {customers && customers.length === 0 ? (
        <p className="empty-state">
          No customers yet. <Link to={settingsLink()}>Add a customer</Link> and pick its enrollments.
        </p>
      ) : null}
      <h2 className="azure-cost-section-title">Per customer</h2>
      <div className="azure-cost-report-grid">
        {REPORTS.map((report) => (
          <Link key={report} to={reportLink(report)} className="card azure-cost-report-card">
            <strong>{REPORT_SUMMARIES[report].title}</strong>
            <span className="text-muted">{REPORT_SUMMARIES[report].summary}</span>
          </Link>
        ))}
      </div>
      <h2 className="azure-cost-section-title">Across all customers</h2>
      <div className="azure-cost-report-grid">
        <Link to="/azure-cost-manager/growth" className="card azure-cost-report-card">
          <strong>Growth and churn</strong>
          <span className="text-muted">Who is growing and who is falling away: three and twelve months against the ones before, services that stopped or started, and each solution play's move.</span>
        </Link>
        <Link to="/azure-cost-manager/whitespace" className="card azure-cost-report-card">
          <strong>Service whitespace</strong>
          <span className="text-muted">The services most other customers use and this one does not, by solution play — each one an opportunity to create.</span>
        </Link>
        <Link to="/azure-cost-manager/marketplace-whitespace" className="card azure-cost-report-card">
          <strong>Marketplace whitespace</strong>
          <span className="text-muted">What customers buy from publishers other than Core42, by category — MACC spend a Core42 offer could compete for.</span>
        </Link>
        <Link to="/azure-cost-manager/marketplace" className="card azure-cost-report-card">
          <strong>Marketplace, all customers</strong>
          <span className="text-muted">Every partner solution, who bought it, and how much counts toward the MACCs.</span>
        </Link>
        <Link to="/azure-cost-manager/finops" className="card azure-cost-report-card">
          <strong>Optimization opportunities</strong>
          <span className="text-muted">Every customer ranked by steady on-demand spend and commitment coverage: where to start the savings conversation.</span>
        </Link>
        <Link to="/azure-cost-manager/renewals" className="card azure-cost-report-card">
          <strong>Marketplace renewals</strong>
          <span className="text-muted">When each recurring Marketplace purchase next charges, and for how much — and the ones that did not renew.</span>
        </Link>
        <Link to="/azure-cost-manager/hygiene" className="card azure-cost-report-card">
          <strong>Subscription and tag hygiene</strong>
          <span className="text-muted">Each customer's subscriptions — new, dormant, tiny, concentrated — beside how much of its spend is tagged.</span>
        </Link>
        <Link to="/azure-cost-manager/tags" className="card azure-cost-report-card">
          <strong>Tag coverage</strong>
          <span className="text-muted">How much of each customer's spend carries environment, project and the other business tags.</span>
        </Link>
      </div>
    </div>
  );
}
