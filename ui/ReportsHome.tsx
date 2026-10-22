import { useEffect, useState } from 'react';
import { Link, Navigate, useLocation } from 'react-router';
import { pluginSettingsLink } from '../../pluginHost/breadcrumbs';
import { fetchCustomers, fetchSignIn, type Customer, type SignInState } from './client';
import { errorText } from './format';

export const REPORT_PATH = '/azure-cost-manager/report';

export const REPORTS = ['Overview', 'This month', 'Forecast', 'Quota', 'Pipeline', 'Marketplace', 'FinOps', 'Tags', 'Breakdown'] as const;
export type Report = typeof REPORTS[number];

const REPORT_SUMMARIES: Record<Report, { title: string; summary: string }> = {
  Overview: { title: 'Consumption overview', summary: 'Signed MACC, MACC consumed, monthly consumption, top services and anomalies.' },
  'This month': { title: 'This month', summary: 'This month so far, day by day: pace against last month and every new service, subscription or resource group -- early signs of an opportunity.' },
  Forecast: { title: 'Forecast', summary: 'Run rate and where consumption lands by the end of the term.' },
  Quota: { title: 'Quota', summary: 'The fiscal year against the baseline: what the customer added above the line, where the year lands, and the pipeline\'s plan against what happened.' },
  Pipeline: { title: 'Pipeline', summary: 'The customer\'s Opportunities and their effect on consumption.' },
  Marketplace: { title: 'Marketplace', summary: 'The partner solutions one customer bought, and how much of its MACC they consumed.' },
  FinOps: { title: 'FinOps', summary: 'Commitment coverage, steady on-demand spend to commit, purchases, growth and the budget.' },
  Tags: { title: 'Tags', summary: 'Cost by environment, project, application, business unit, owner and cost centre tags.' },
  Breakdown: { title: 'Breakdown', summary: 'Consumption by service, subscription and resource group.' },
};

type ThemeItem = { report: Report } | { to: string; title: string; summary: string };

// Grouped by what the operator is after, one customer's reports beside the ones
// across all customers (operator, 2026-10-21: "the reports need a different grouping").
const THEMES: { title: string; items: ThemeItem[] }[] = [
  { title: 'Consumption and MACC', items: [
    { report: 'Overview' }, { report: 'This month' }, { report: 'Forecast' }, { report: 'Breakdown' },
    { to: '/azure-cost-manager/growth', title: 'Growth and churn',
      summary: 'Who is growing and who is falling away: three and twelve months against the ones before, services that stopped or started, and each solution play\'s move.' },
  ] },
  { title: 'Quota and forecast', items: [
    { report: 'Quota' },
    { to: '/azure-cost-manager/quota', title: 'Baseline and quota',
      summary: 'Every customer above its baseline and your quota\'s attainment — to date, projected and with the pipeline — and the opportunities that missed their forecast.' },
  ] },
  { title: 'Opportunities', items: [
    { report: 'Pipeline' },
    { to: '/azure-cost-manager/whitespace', title: 'Service whitespace',
      summary: 'The services most other customers use and this one does not, by solution play — each one an opportunity to create.' },
    { to: '/azure-cost-manager/marketplace-whitespace', title: 'Marketplace whitespace',
      summary: 'What customers buy from publishers other than Core42, by category — MACC spend a Core42 offer could compete for.' },
  ] },
  { title: 'Marketplace', items: [
    { report: 'Marketplace' },
    { to: '/azure-cost-manager/marketplace', title: 'Marketplace, all customers',
      summary: 'Every partner solution, who bought it, and how much counts toward the MACCs.' },
    { to: '/azure-cost-manager/renewals', title: 'Marketplace renewals',
      summary: 'When each recurring Marketplace purchase next charges, and for how much — and the ones that did not renew.' },
  ] },
  { title: 'Optimization and governance', items: [
    { report: 'FinOps' }, { report: 'Tags' },
    { to: '/azure-cost-manager/finops', title: 'Optimization opportunities',
      summary: 'Every customer ranked by steady on-demand spend and commitment coverage: where to start the savings conversation.' },
    { to: '/azure-cost-manager/tags', title: 'Tag coverage',
      summary: 'How much of each customer\'s spend carries environment, project and the other business tags.' },
    { to: '/azure-cost-manager/hygiene', title: 'Subscription and tag hygiene',
      summary: 'Each customer\'s subscriptions — new, dormant, tiny, concentrated — beside how much of its spend is tagged.' },
  ] },
];

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
      {THEMES.map((theme) => (
        <section key={theme.title}>
          <h2 className="azure-cost-section-title">{theme.title}</h2>
          <div className="azure-cost-report-grid">
            {theme.items.map((item) => {
              const to = 'report' in item ? reportLink(item.report) : item.to;
              const title = 'report' in item ? REPORT_SUMMARIES[item.report].title : item.title;
              const summary = 'report' in item ? REPORT_SUMMARIES[item.report].summary : item.summary;
              return (
                <Link key={to} to={to} className="card azure-cost-report-card">
                  <span className={`azure-cost-report-scope ${'report' in item ? 'one' : 'all'}`}>
                    {'report' in item ? 'One customer' : 'All customers'}</span>
                  <strong>{title}</strong>
                  <span className="text-muted">{summary}</span>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
