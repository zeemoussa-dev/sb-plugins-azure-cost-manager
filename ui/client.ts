import { apiFetch } from '../../pluginHost/api';

// The host mounts this plugin's backend under /plugins/<plugin-id>/.
const BASE = '/plugins/azure-cost-manager';

export interface SignInState {
  signed_in: boolean;
  message: string | null;
}

export interface BillingAccount {
  name: string;
  display_name: string;
  agreement_type: string;
  account_type?: string | null;
  /** An EA enrollment's term, when Azure reports one. */
  term_start?: string | null;
  term_end?: string | null;
  /** Accounts sharing a key are probably one customer: a renewal, or linked under one parent. */
  group_key: string;
  /** The customer this account already belongs to, if any. */
  customer: string | null;
}

export interface Commitment {
  type: string;
  amount: number;
  currency: string;
  start: string;
  end: string;
  note?: string;
  /** Marketplace burns a MACC; a credit lowers what was billed against it. */
  include_marketplace?: boolean;
  subtract_credits?: boolean;
  /** A parent's affiliates: "roll up" (their consumption burns this MACC) or "own" (each signed its own). */
  affiliates?: 'roll up' | 'own';
}

export interface Measure {
  /** All Marketplace, none, or only Core42's own offers -- which makes the totals Core42's revenue. */
  marketplace: boolean | 'core42';
  credits: boolean;
}

export interface ScenarioSettings {
  growth: { Base: number; Upside: number; Downside: number };
  seasonality: boolean;
  active: 'Base' | 'Upside' | 'Downside';
  uplift_usd: number;
  uplift_from: string | null;
}

export interface PlanMonth {
  month: string;
  usd: number;
}

export interface Opportunity {
  id: string;
  title: string;
  stem?: string;
  customer: string;
  affiliate: string | null;
  status: string;
  stage: string;
  /** Lists: an opportunity can carry several products and partners. */
  product?: string[];
  route?: string;
  partner?: string[];
  billing_profile?: string;
  consumption_start?: string;
  expected_monthly_usd?: number | string;
  plan: PlanMonth[];
  updated?: string;
}

export interface PipelineState {
  available: boolean;
  reason: string | null;
  linked?: boolean;
  opportunities: Opportunity[];
  by_month: Record<string, number>;
}

/** A note a customer can be linked to: a Customer or (Entities 1.5+) a Partner,
 *  with its affiliates nested to any depth. */
export interface EntityCustomer {
  name: string;
  stem: string;
  tag: string;
  kind?: 'customer' | 'partner';
  affiliates: EntityCustomer[];
}

/** Every note in a hub tree, parents before their affiliates, with its depth. */
export function flattenHubs(hubs: EntityCustomer[], depth = 0, parent: EntityCustomer | null = null):
  { hub: EntityCustomer; depth: number; parent: EntityCustomer | null }[] {
  return hubs.flatMap((hub) => [{ hub, depth, parent }, ...flattenHubs(hub.affiliates ?? [], depth + 1, hub)]);
}

export function findHub(hubs: EntityCustomer[], stem: string): EntityCustomer | undefined {
  return flattenHubs(hubs).find((entry) => entry.hub.stem === stem)?.hub;
}

export interface CustomerAccount {
  name: string;
  display_name: string;
  agreement_type: string | null;
  term_start: string | null;
  term_end: string | null;
  synced_at: string | null;
  errors: Record<string, string>;
}

export interface Customer {
  id: string;
  name: string;
  accounts: CustomerAccount[];
  commitment: Commitment | null;
  synced_at: string | null;
  /** The Entities Customer note whose Opportunities are this customer's pipeline. */
  entity_customer?: string | null;
  scenario?: ScenarioSettings | null;
  /** The group this customer is an affiliate of; its MACC is carved out of the parent's. */
  parent?: string | null;
  /** Ids of this customer's affiliates, when it is a parent. */
  affiliates?: string[];
  /** Where the signed value lives: the linked Customer note in the vault, or this plugin's settings. */
  commitment_source?: 'note' | 'settings';
  /** Why the note's signed value cannot be used -- e.g. left incomplete in Obsidian. */
  commitment_problem?: string | null;
  /** Overrides the FinOps budget, which is otherwise the MACC spread over its term. */
  budget_monthly?: number | null;
}

export interface CustomerDraft {
  name: string;
  accounts: string[];
  commitment: Partial<Commitment> | null;
  entity_customer?: string | null;
  parent?: string | null;
  budget_monthly?: number | null;
}

export interface GroupInfo {
  parent: {
    id: string; name: string; amount: number | null; currency: string | null; entity_customer: string | null;
    /** Its consumption counts toward this parent's MACC (the parent's affiliates roll up). */
    rolls_up?: boolean;
  } | null;
  affiliates: { id: string; name: string }[];
  /** `member`/`member_id`: whose enrollment it is; `short_name` drops a linked one's "<parent>-<number>-" prefix. */
  accounts: (CustomerAccount & { member: string; member_id?: string; short_name?: string })[];
}

export interface Allocations {
  parent_amount: number | null;
  allocated: number;
  unallocated: number | null;
  over_allocated: boolean;
  own: { consumed: number; remaining: number | null };
  affiliates: { id: string; name: string; commitment: Commitment | null; burn: BurnDown | null; consumed_against_parent: number }[];
  consumed_total: number;
}

export interface MonthTotal {
  month: string;
  /** The measured total: what the dashboard means by consumption. */
  actual: number;
  amortized: number;
  cost_management: number;
  usage: number;
  marketplace: number;
  credits: number;
  mom_pct: number | null;
  yoy_pct?: number | null;
  /** The current month: still being billed, never compared or used as evidence. */
  partial: boolean;
}

export interface BreakdownRow {
  name: string;
  cost: number;
  share_pct: number;
  previous: number;
  change_pct: number | null;
}

export interface Breakdown {
  month: string;
  total: number;
  rows: BreakdownRow[];
  others: number;
}

export interface Anomaly {
  service: string;
  month: string;
  kind: 'spike' | 'drop' | 'new';
  cost: number;
  baseline: number;
  change: number;
  change_pct: number | null;
}

export interface BurnDown extends Commitment {
  consumed: number;
  remaining: number;
  consumed_pct: number;
  elapsed_pct: number;
  on_pace: number;
  pace_gap: number;
  run_rate: number | null;
  projected_at_end: number;
  projected_shortfall: number;
  pipeline_in_term: number;
  projected_with_pipeline: number;
  shortfall_with_pipeline: number;
  projected_exhaustion: string | null;
  cumulative: { month: string; consumed: number; partial: boolean }[];
  verdict: string;
}

export interface ForecastMonth {
  month: string;
  cost: number;
  source: 'azure' | 'run-rate';
}

export interface Forecast {
  source: 'azure' | 'run-rate' | null;
  months: ForecastMonth[];
  year: number;
  year_to_date_closed: number;
  year_end_total: number | null;
}

export interface AutomaticForecast {
  method: string;
  slope: number;
  intercept: number;
  r_squared: number;
  mape: number;
  months_of_history: number;
  seasonal_index: Record<string, number>;
  next_12_months: number;
  next_12_months_with_pipeline: number;
  this_year_total: number;
  next_year: number;
  next_year_total: number;
  next_year_with_pipeline: number;
  next_vs_this_pct: number | null;
  series: { month: string; actual: number | null; model: number | null; forecast: number | null; pipeline: number }[];
}

export interface Scenarios {
  settings: ScenarioSettings;
  base_month: string;
  base_total: number;
  rows: { month: string; Base: number; Upside: number; Downside: number; pipeline: number; active_with_pipeline: number }[];
  totals: Record<string, number>;
  next_year: Record<string, number>;
  pipeline_total: number;
}

export interface DashboardKpis {
  all_time: number;
  months_of_history: number;
  first_month: string | null;
  ytd: number | null;
  ytd_last_year: number | null;
  ytd_growth_pct: number | null;
  ytd_through: string | null;
  latest_month: string | null;
  latest_total: number | null;
  latest_mom_pct: number | null;
  latest_yoy_pct: number | null;
  current_month: string | null;
  current_so_far: number | null;
  active_enrollments: number;
  largest_enrollment_share_pct: number | null;
  burn_rate_3m: number | null;
  next_12_months: number | null;
  next_year_forecast: number | null;
  credits_all_time: number;
  marketplace_all_time: number;
  /** Marketplace bought from Core42 or G42 -- the only Marketplace that is Core42 revenue. */
  core42_marketplace_all_time?: number;
  /** The burn less Marketplace from other publishers; credits as the filter says. */
  core42_revenue_all_time?: number;
  core42_revenue_this_year?: number;
  commitment_consumed_pct?: number;
  commitment_remaining?: number;
  runway_months?: number | null;
  projected_exhaustion?: string | null;
}

export interface Dashboard {
  kpis: DashboardKpis;
  monthly: MonthTotal[];
  by_year: { year: number; total: number; partial: boolean }[];
  ytd_by_year: { year: number; total: number }[];
  mix: { month: string; lines: Record<string, number> }[];
  accounts: string[];
  quarterly: { quarter: string; by_account: Record<string, number> }[];
  this_vs_last_year: {
    this_year: number; last_year: number;
    this: (number | null)[]; last: (number | null)[];
    this_mom: (number | null)[]; last_mom: (number | null)[];
  };
  credit_details: { month: string; name: string; value: number }[];
}

export interface Analysis {
  /** The date the report is as of, after the billing date: before it, the month before is still open. */
  as_of?: string;
  /** The enrollments the figures cover: all of the group's unless some were chosen. */
  shown_accounts?: string[];
  /** Actual cost by solution play per month. */
  solution_plays?: { month: string; by_play: Record<string, number> }[];
  customer: Customer;
  group: GroupInfo;
  allocations: Allocations | null;
  synced_at: string | null;
  stale: boolean;
  errors: Record<string, Record<string, string>>;
  currency: string | null;
  measure: Measure;
  months: MonthTotal[];
  last_closed_month: string;
  top_services: Breakdown;
  subscriptions: Breakdown;
  enrollments: Breakdown;
  anomalies: Anomaly[];
  commitment: BurnDown | null;
  forecast: Forecast;
  automatic_forecast: AutomaticForecast | null;
  scenarios: Scenarios | null;
  gpu_and_ai: { month: string; lines: { category: string; pricing: string; cost: number }[] }[];
  dashboard: Dashboard;
  pipeline: PipelineState;
}

export interface ConsumptionRow {
  month: string;
  name: string;
  cost: number;
}

export type MixGroup = 'service' | 'subscription' | 'account' | 'play';

export interface SyncStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  scope: string | null;
  current: {
    /** Missing or null in stages that are not about one enrollment (pricing). */
    account?: string | null;
    /** Missing in stages that are not about a month range (this month, pricing). */
    first_month?: string; last_month?: string; waiting_seconds?: number;
    display_name?: string;
    /** Reading billing-period balances, one month per call, rather than cost. */
    balances?: boolean;
    /** Reading a billing period's Marketplace charges. */
    marketplace?: boolean;
    amortized_meters?: boolean;
    tags?: boolean;
    tag?: string;
    this_month?: boolean;
    pricing?: boolean;
  } | null;
  accounts_done: number;
  accounts_total: number;
  errors: { account: string | null; message: string }[];
  /** When the step in `current` began; a wait inside it does not restart it. */
  step_started_at?: string | null;
  /** The Azure request on the wire right now, and since when. */
  in_flight?: { what: string; since: string } | null;
  started?: boolean;
  reason?: string;
}

export interface SyncRun {
  id: string;
  scope: string;
  started_at: string;
  finished_at: string | null;
  /** running, finished, finished with errors, stopped, or interrupted (the backend restarted). */
  outcome: string;
  requests: number;
  pages: number;
  throttle_waits: number;
  waited_seconds: number;
  errors: number;
  dropped_events: number;
}

export interface SyncEvent {
  at: string;
  kind: 'step' | 'request' | 'wait' | 'error' | 'interrupted' | 'note';
  text: string;
  account?: string;
  seconds?: number;
  status?: number;
}

export interface MarketplaceSolution {
  publisher: string;
  offer: string;
  plan: string;
  macc_eligible: boolean;
  total: number;
  by_month: Record<string, number>;
  subscriptions: string[];
  enrollments: string[];
  kind: 'SaaS' | 'Metered' | 'SaaS + metered';
  quantity: number;
  unit: string;
  first_month: string;
  last_month: string;
}

export interface MarketplacePeriod {
  first: string | null;
  last: string | null;
  /** True when the report runs from the first month on record. */
  from_start: boolean;
}

export interface MarketplaceReport {
  customer: { id: string; name: string };
  period: MarketplacePeriod;
  total: number;
  macc: number;
  not_macc: number;
  solutions: MarketplaceSolution[];
  adopted: MarketplaceSolution[];
  publishers: { publisher: string; total: number; macc: number; solutions: number }[];
  monthly: { month: string; total: number; macc: number; not_macc: number; by_publisher: Record<string, number> }[];
  reconciliation: { account: string; month: string; itemised: number; invoiced: number }[];
}

export interface MarketplaceAcross {
  period: MarketplacePeriod;
  total: number;
  macc: number;
  not_macc: number;
  solutions: {
    publisher: string; offer: string; macc_eligible: boolean; total: number; macc: number; plans: string[];
    customers: { name: string; total: number }[]; adopted_by: number; by_month: Record<string, number>; kind: string;
  }[];
  publishers: { publisher: string; total: number; macc: number; solutions: number; customers: string[] }[];
  customers: {
    id: string; name: string; parent: string | null; total: number; macc: number; solutions: number;
    top_publisher: string | null;
    /** A billing profile that is no customer yet, synced lightly. */
    profile: boolean;
    accounts: string[];
    /** Invoiced consumption in the period: the denominator for the Marketplace share. */
    consumption: number;
  }[];
  monthly: { month: string; total: number; macc: number }[];
}

const customer = (id: string) => `${BASE}/customers/${encodeURIComponent(id)}`;
const periodQuery = (first?: string, last?: string) =>
  [first ? `first_month=${first}` : '', last ? `last_month=${last}` : ''].filter(Boolean).join('&');

export const fetchCustomerMarketplace = (id: string, first?: string, last?: string, accounts?: string[]) =>
  apiFetch<MarketplaceReport>(`${customer(id)}/marketplace?${periodQuery(first, last)}${accountsQuery(accounts)}`);

export const fetchMarketplaceAcross = (first?: string, last?: string) =>
  apiFetch<MarketplaceAcross>(`${BASE}/marketplace?${periodQuery(first, last)}`);

export const setMaccEligible = (publisher: string, offer: string, eligible: boolean) =>
  apiFetch<{ publisher: string; offer: string }[]>(`${BASE}/marketplace/macc-eligibility`,
    { method: 'PUT', body: JSON.stringify({ publisher, offer, eligible }) });

/** A path for an `<a href>`: the browser downloads the workbook itself. */
export const marketplaceExportPath = (first?: string, last?: string) =>
  `${BASE}/marketplace/export.xlsx?${periodQuery(first, last)}`;

export const fetchSignIn = () => apiFetch<SignInState>(`${BASE}/sign-in`);

export const fetchBillingAccounts = (fresh = false) =>
  apiFetch<BillingAccount[]>(`${BASE}/billing-accounts${fresh ? '?fresh=true' : ''}`);

export const fetchCommitmentTypes = () => apiFetch<string[]>(`${BASE}/commitment-types`);

export const fetchCustomers = () => apiFetch<Customer[]>(`${BASE}/customers`);

/** Enrollments in no customer, grouped as Settings suggests, with what they consumed. */
export interface UnassignedGroup {
  key: string;
  name: string;
  accounts: { name: string; display_name: string; agreement_type: string | null; term_start: string | null;
    term_end: string | null; last_month: number; last_twelve_months: number }[];
  last_month: number;
  last_month_label: string;
  last_twelve_months: number;
  /** False when no billing period of it has been synced: nothing to say about its spend yet. */
  synced: boolean;
}

export const fetchUnassigned = () => apiFetch<UnassignedGroup[]>(`${BASE}/unassigned`);

export type PortfolioStatus = 'not-synced' | 'no-macc' | 'parent-macc' | 'consumed' | 'behind' | 'early' | 'on-track';

/** One customer at a glance; a parent's figures include its affiliates. */
export interface PortfolioRow {
  id: string;
  name: string;
  parent: string | null;
  /** The parent whose MACC this affiliate consumes, when it signed none of its own. */
  covered_by?: string | null;
  affiliates: string[];
  enrollments: number;
  currency: string | null;
  signed: number | null;
  /** What the affiliates signed, carved out of a parent's MACC. */
  allocated: number | null;
  burn: {
    consumed: number; remaining: number; consumed_pct: number; elapsed_pct: number;
    projected_at_end: number; projected_shortfall: number; projected_exhaustion: string | null; end: string;
  } | null;
  last_month: { month: string; actual: number; mom_pct: number | null } | null;
  recent: { month: string; actual: number }[];
  status: PortfolioStatus;
  synced_at: string | null;
  /** Enrollments in the row (a group's: its affiliates' too) not synced yet. */
  unsynced_enrollments: number;
  stale: boolean;
}

export const fetchPortfolio = () => apiFetch<PortfolioRow[]>(`${BASE}/portfolio`);

export const saveCustomer = (id: string | null, draft: CustomerDraft) =>
  apiFetch<Customer>(id ? customer(id) : `${BASE}/customers`, {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  });

export const deleteCustomer = (id: string) => apiFetch<{ deleted: string }>(customer(id), { method: 'DELETE' });

const measureQuery = (measure: Measure) => `marketplace=${measure.marketplace}&credits=${measure.credits}`;

/** Who a page or workbook is for: the operator, or the customer it is about. The
 *  Customer view leaves out the forecast scenarios, on the server. */
export type View = 'account' | 'customer';

const accountsQuery = (accounts?: string[]) =>
  accounts?.length ? `&accounts=${encodeURIComponent(accounts.join(','))}` : '';
/** The same, as a path's only query. */
const onlyAccounts = (accounts?: string[]) =>
  accounts?.length ? `?accounts=${encodeURIComponent(accounts.join(','))}` : '';

/** `accounts`: only these of the group's enrollments; none given shows them all. */
export const fetchAnalysis = (id: string, measure: Measure, view: View = 'account', accounts?: string[]) =>
  apiFetch<Analysis>(`${customer(id)}/analysis?${measureQuery(measure)}&view=${view}${accountsQuery(accounts)}`);

/** A path for an `<a href>`: the browser downloads the workbook itself. */
export const exportPath = (id: string, measure: Measure, view: View = 'account', accounts?: string[]) =>
  `${customer(id)}/export.xlsx?${measureQuery(measure)}&view=${view}${accountsQuery(accounts)}`;

export interface CoverageFamily { family: string; covered: number; on_demand: number; coverage_pct: number | null }
export interface CoverageMonth extends CoverageFamily { month: string; families: CoverageFamily[] }

export type CommitmentOption = 'sp_1y' | 'sp_3y' | 'ri_1y' | 'ri_3y';

export const OPTION_LABELS: Record<CommitmentOption, string> = {
  sp_1y: '1-year savings plan', sp_3y: '3-year savings plan', ri_1y: '1-year reservation', ri_3y: '3-year reservation',
};

export interface SteadyCandidate {
  meter: string;
  family: string;
  monthly_on_demand: number;
  lowest_month: number;
  variation_pct: number;
  annual_on_demand: number;
  months: Record<string, number>;
  /** Estimated monthly saving per option, from the public price list; null when not priced. */
  savings: Partial<Record<CommitmentOption, number>> | null;
  priced_as: string | null;
  not_priced: string | null;
}

export interface Growth { name: string; monthly_now: number; monthly_before: number; change: number; change_pct: number | null }

export interface Budget {
  amount: number;
  /** "set" in Settings, or "macc": the MACC spread over its term. */
  source: 'set' | 'macc';
  term_months?: number;
  last_month: string | null;
  last_month_actual: number | null;
  current_month_forecast: number | null;
  over_in_last_12: string[];
  status: 'over' | 'forecast-over' | 'within';
}

export interface FinOps {
  customer: { id: string; name: string; parent: string | null; affiliates: string[]; entity_customer: string | null };
  currency: string | null;
  pricing_region: string;
  savings_monthly: Partial<Record<CommitmentOption, number>>;
  has_meters: boolean;
  has_amortized_meters: boolean;
  coverage: { months: CoverageMonth[]; latest: CoverageMonth | null };
  candidates: SteadyCandidate[];
  candidates_monthly: number;
  purchases: { month: string; charged: number; amortized: number; bought_up_front: number }[];
  growth: { services: Growth[]; subscriptions: Growth[] };
  budget: Budget | null;
  /** The license meters Azure Hybrid Benefit could take off, if the customer holds the licenses. */
  hybrid_benefit: { product: string; program: string; meters: Record<string, number>; monthly: number }[];
  /** Each up-front purchase and when it would renew on a 1- or 3-year term. */
  renewals: { bought: string; amount: number; renews_if: Record<'1y' | '3y', string>; soon: ('1y' | '3y')[] }[];
  /** What looks like waste, to ask the customer's engineers about. */
  waste: { subscription: string; kind: string; monthly_at_stake: number; detail: string }[];
}

export interface SavingsMove {
  kind: 'reserve' | 'savings_plan' | 'hybrid_benefit' | 'keep_on_demand' | 'investigate';
  ref: string;
  /** Only a subscription can be drilled into. */
  subject: 'meter' | 'license' | 'subscription';
  option: CommitmentOption | null;
  monthly: number | null;
  saving_monthly: number | null;
  why: string;
  risk: 'low' | 'medium' | 'high';
  risk_reason: string;
}

export interface SavingsPlan {
  summary: string;
  moves: SavingsMove[];
  reinvest: string;
  questions: string[];
}

export interface FinOpsAcrossRow {
  id: string;
  name: string;
  affiliates: string[];
  currency: string | null;
  has_meters: boolean;
  coverage_pct: number | null;
  on_demand: number | null;
  coverage_month: string | null;
  candidates: number;
  candidates_monthly: number;
  top_candidate: string | null;
  savings_monthly: Partial<Record<CommitmentOption, number>>;
  budget: Budget | null;
}

export const fetchFinOps = (id: string, accounts?: string[]) => apiFetch<FinOps>(`${customer(id)}/finops${onlyAccounts(accounts)}`);
export const fetchSavingsPlan = (id: string, accounts?: string[]) =>
  apiFetch<Kept<SavingsPlan>>(`${customer(id)}/finops/plan${onlyAccounts(accounts)}`);
export const writeSavingsPlan = (id: string, accounts?: string[]) =>
  apiFetch<Kept<SavingsPlan>>(`${customer(id)}/finops/plan${onlyAccounts(accounts)}`, { method: 'POST' });
export const fetchSavingsReport = (id: string, accounts?: string[]) =>
  apiFetch<Kept<string>>(`${customer(id)}/finops/report${onlyAccounts(accounts)}`);
export const writeSavingsReport = (id: string, accounts?: string[]) =>
  apiFetch<Kept<string>>(`${customer(id)}/finops/report${onlyAccounts(accounts)}`, { method: 'POST' });
export const fetchFinOpsAcross = () => apiFetch<FinOpsAcrossRow[]>(`${BASE}/finops`);
export interface MonthRow {
  name: string;
  this_month: number;
  last_month_same_days: number;
  change: number;
  change_pct: number | null;
  new: boolean;
}

export interface ThisMonth {
  customer: { id: string; name: string; entity_customer: string | null };
  currency: string | null;
  has_data: boolean;
  fetched_at?: string;
  /** Enrollments the last refresh never reached: their spend is absent from every figure. */
  missing_enrollments?: string[];
  month?: string;
  /** The last day Azure has data for -- it lags a day or two. */
  through?: string | null;
  days_elapsed?: number;
  days_in_month?: number;
  month_to_date?: number;
  last_month_same_days?: number;
  pace_pct?: number | null;
  projected_month_end?: number | null;
  last_month_total?: number;
  daily?: { day: number; this_month: number | null; last_month: number | null;
    this_month_to_date: number | null; last_month_to_date: number | null }[];
  /** service, subscription, resource_group, and tag:Project / tag:Owner / tag:Environment
   *  where the refresh found those tags. `rows` is every name, largest first. */
  dimensions?: Record<string, { label: string; movers: MonthRow[]; new: MonthRow[]; rows: MonthRow[] }>;
  new_workloads?: { kind: string; kind_label: string; name: string; this_month: number }[];
}

export const fetchThisMonth = (id: string, accounts?: string[]) =>
  apiFetch<ThisMonth>(`${customer(id)}/this-month${onlyAccounts(accounts)}`);
/** Last month and this one by day; every customer's enrollments without `customerId`. */
export const refreshThisMonth = (customerId?: string) =>
  apiFetch<SyncStatus & { started: boolean }>(`${BASE}/sync/this-month${customerId ? `?customer=${encodeURIComponent(customerId)}` : ''}`,
    { method: 'POST' });

export interface TagDimension {
  dimension: string;
  /** The tag keys queried for it, at most four, exact spellings first. */
  spellings: string[];
  /** Every key on the enrollments that spells it -- the hygiene view. */
  all_spellings: string[];
  /** Per month, cost by folded value; "(untagged)" is what no spelling tagged. */
  months: Record<string, Record<string, number>>;
  last_month: string | null;
  coverage_pct: number | null;
  values: number;
}

export interface TagsReport {
  customer: { id: string; name: string };
  currency: string | null;
  synced: boolean;
  tag_keys: number;
  dimensions: TagDimension[];
  /** Where tagging falls short against the six business dimensions. */
  gaps?: TagGaps;
}

export interface TagsAcrossRow {
  id: string;
  name: string;
  synced: boolean;
  tag_keys: number;
  coverage: Record<string, number | null>;
  spellings: Record<string, number>;
}

export interface TagGapDimension {
  dimension: string;
  used: boolean;
  coverage_pct?: number | null;
  below_target?: boolean;
  untagged_last_month?: number;
  last_month?: string | null;
  coverage_trend?: { month: string; coverage_pct: number }[];
  spellings?: string[];
  values?: number;
  value_drift?: { value: string; written_as: string[]; cost: number }[];
}

export interface TagGaps {
  standard: string[];
  coverage_target_pct: number;
  tag_keys: number;
  dimensions: TagGapDimension[];
  missing: string[];
  environment_in_subscription_names: {
    subscriptions: number; of_subscriptions: number; monthly: number; share_pct: number | null;
    by_environment: Record<string, number>;
  };
}

export interface TaggingMove {
  kind: 'adopt_key' | 'standardize_key' | 'normalize_values' | 'inherit' | 'enforce_policy' | 'backfill' | 'allocate_untagged';
  dimension: string;
  coverage_pct: number | null;
  untagged_last_month: number | null;
  detail: string;
  why: string;
  effort: 'low' | 'medium' | 'high';
}

export interface TaggingPlan {
  summary: string;
  moves: TaggingMove[];
  offer: string;
  questions: string[];
}

export const fetchTaggingPlan = (id: string, accounts?: string[]) =>
  apiFetch<Kept<TaggingPlan>>(`${customer(id)}/tags/plan${onlyAccounts(accounts)}`);
export const writeTaggingPlan = (id: string, accounts?: string[]) =>
  apiFetch<Kept<TaggingPlan>>(`${customer(id)}/tags/plan${onlyAccounts(accounts)}`, { method: 'POST' });
export const fetchTaggingGuide = (id: string, accounts?: string[]) =>
  apiFetch<Kept<string>>(`${customer(id)}/tags/guide${onlyAccounts(accounts)}`);
export const writeTaggingGuide = (id: string, accounts?: string[]) =>
  apiFetch<Kept<string>>(`${customer(id)}/tags/guide${onlyAccounts(accounts)}`, { method: 'POST' });

export const UNTAGGED = '(untagged)';
export const fetchTags = (id: string, accounts?: string[]) => apiFetch<TagsReport>(`${customer(id)}/tags${onlyAccounts(accounts)}`);
export const fetchTagsAcross = () => apiFetch<TagsAcrossRow[]>(`${BASE}/tags`);
export const startTagSync = (customerId?: string) =>
  apiFetch<SyncStatus & { started: boolean }>(`${BASE}/sync/tags${customerId ? `?customer=${encodeURIComponent(customerId)}` : ''}`,
    { method: 'POST' });

export const refreshPrices = () =>
  apiFetch<{ priced: number; failed: string[] }>(`${BASE}/finops/prices`, { method: 'POST' });

export const saveScenario = (id: string, settings: ScenarioSettings) =>
  apiFetch<ScenarioSettings>(`${customer(id)}/scenario`, { method: 'PUT', body: JSON.stringify(settings) });

export const createAffiliateNote = (customerStem: string, name: string) =>
  apiFetch<{ name: string; stem: string; tag: string }>(
    `${BASE}/entity-customers/${encodeURIComponent(customerStem)}/affiliates`,
    { method: 'POST', body: JSON.stringify({ name }) });

export const fetchEntityCustomers = () =>
  apiFetch<{ available: boolean; reason?: string; customers: EntityCustomer[]; commitments_on_notes?: boolean }>(
    `${BASE}/entity-customers`);

export const createOpportunity = (id: string, ownerStem: string, title: string,
  fields: Partial<Opportunity>, plan: PlanMonth[]) =>
  apiFetch<Opportunity>(`${customer(id)}/opportunities`, {
    method: 'POST', body: JSON.stringify({ owner_stem: ownerStem, title, fields, plan }),
  });

export const updateOpportunity = (opportunityId: string, fields: Partial<Opportunity>, plan: PlanMonth[] | null) =>
  apiFetch<Opportunity>(`${BASE}/opportunities/${encodeURIComponent(opportunityId)}`, {
    method: 'PUT', body: JSON.stringify({ fields, plan }),
  });

/** `accounts`: only these of the group's enrollments, as the report's Enrollments choice. */
export const fetchConsumption = (id: string, group: MixGroup, accounts?: string[]) =>
  apiFetch<{ rows: ConsumptionRow[] }>(`${customer(id)}/consumption?group=${group}&cost=actual${accountsQuery(accounts)}`);

export interface SolutionPlaysSettings {
  plays: string[];
  services: { service: string; spend: number; play: string; default: string | null; changed: boolean }[];
  /** Services no mapping names: they count as Unassigned. */
  unmapped: string[];
  gpu_rule: string;
}

export interface GrowthRow {
  id: string;
  name: string;
  parent: string | null;
  affiliates: number;
  currency: string | null;
  status: 'growing' | 'declining' | 'steady' | 'new' | 'no data';
  last_month: string | null;
  last_total?: number;
  recent_monthly?: number;
  before_monthly?: number | null;
  change_3m_pct?: number | null;
  change_12m_pct?: number | null;
  yoy_pct?: number | null;
  signals: { kind: 'growing' | 'declining' | 'drop' | 'stopped' | 'new'; text: string }[];
  stopped?: { service: string; before: number; last: number }[];
  started?: { service: string; last: number }[];
  by_play?: { play: string; recent: number; before: number; change: number; change_pct: number | null }[];
}

export interface WhitespaceRow {
  id: string;
  name: string;
  entity_customer: string | null;
  currency: string;
  /** How many services it uses ($500 a month or more), and its monthly spend. */
  uses: number;
  monthly: number;
  gaps: { service: string; play: string; users: number; adoption_pct: number; typical_monthly: number }[];
}

export interface MarketplaceWhitespace {
  period: { first: string | null; last: string; from_start: boolean } | null;
  third_party: number;
  core42: number;
  core42_share_pct: number | null;
  categories: {
    category: string; total: number; macc_eligible: number; customers: number;
    solutions: { publisher: string; offer: string; total: number; customers: number; kind?: string; macc_eligible: boolean }[];
  }[];
  customers: {
    name: string; third_party: number; macc_eligible: number; core42: number; core42_share_pct: number | null;
    by_category: Record<string, number>;
  }[];
}

export const fetchMarketplaceWhitespace = () => apiFetch<MarketplaceWhitespace>(`${BASE}/marketplace/whitespace`);

export interface HygieneRow {
  id: string;
  name: string;
  last_month: string;
  subscriptions: number;
  subscriptions_12m: number;
  tiny: number;
  top_share_pct: number | null;
  top3_share_pct: number | null;
  new: { subscription: string; last: number }[];
  new_count: number;
  dormant: { subscription: string; before: number; last: number }[];
  dormant_count: number;
  tags_synced: boolean;
  tag_coverage: Record<string, number | null>;
}

export const fetchHygiene = () => apiFetch<HygieneRow[]>(`${BASE}/hygiene`);

export interface RenewalRow {
  customer: string;
  publisher: string;
  offer: string;
  plan: string;
  subscription: string;
  core42: boolean;
  cadence: string;
  cadence_months: number;
  /** Charged once: taken as yearly, the common SaaS term. */
  cadence_assumed: boolean;
  last_month: string;
  last_amount: number;
  charges: number;
  next_month: string;
  status: 'overdue' | 'due this month' | 'upcoming';
}

export const fetchRenewals = () => apiFetch<RenewalRow[]>(`${BASE}/marketplace/renewals`);

/** The cross-customer reports that export to Excel. */
export type ExportedReport = 'growth' | 'whitespace' | 'marketplace-whitespace' | 'hygiene' | 'renewals' | 'quota'
  | 'solutions';
/** `measure`: for a report counted under the Marketplace and credits filters (quota). */
export const reportExportPath = (report: ExportedReport, measure?: Measure) =>
  `${BASE}/reports/${report}/export.xlsx${measure ? `?${measureQuery(measure)}` : ''}`;

/** One service, subscription, solution play or month opened up (operator, 2026-10-23). */
export type DrillKind = 'service' | 'subscription' | 'play' | 'month';

export interface Drill {
  customer: { id: string; name: string };
  currency: string | null;
  kind: DrillKind;
  name: string;
  trend?: { month: string; cost: number }[];
  parts_kind: DrillKind;
  parts: ({ name: string; monthly: number; last_12: number | null; technology_note?: string | null }
    | { name: string; cost: number; before: number })[];
  recent_months?: string[];
  pairs_missing?: boolean;
  /** The breakdown came from the tags sync's last closed months: the history has no pairs yet. */
  from_footprint?: boolean;
  play?: string;
  technology_note?: string | null;
  solutions?: { id: string; name: string; note?: string | null }[];
  resource_groups?: { name: string; monthly: number }[];
  /** For "SaaS" and "Azure Applications": the Marketplace products they are. */
  marketplace?: { publisher: string; offer: string; plan: string; subscriptions: string[]; monthly: number; recurring?: boolean }[];
  total?: number;
  previous?: string | null;
  subscriptions?: { name: string; cost: number }[];
  by_play?: { name: string; cost: number }[];
}

/** A Compass answer kept with the fingerprint of the facts it was written from. */
export interface Kept<T> {
  value: T | null;
  at: string | null;
  kept: boolean;
  stale: boolean;
  available: boolean;
}

export interface NextAction {
  customer_id: string;
  customer: string;
  action: string;
  why: string;
  urgency: 'now' | 'this quarter' | 'later';
  pitch: string | null;
  /** Small, medium, large -- the Solution note's sizing, never Compass's. */
  sized_monthly: number[] | null;
  last_month: number | null;
}

export interface DraftOpportunity {
  title: string;
  summary: string;
  size: 'small' | 'medium' | 'large';
  expected_monthly: number | null;
  next_steps: string[];
  email_subject: string;
  email_body: string;
  solution: string;
}

export interface SizedSolution {
  solution: string;
  note: string | null;
  rows: { block: string; service: string; size: string; factor: number; list_monthly: number; monthly: number;
    basis: string | null; reason: string }[];
  total: number;
  assumptions: string[];
  questions: string[];
}

export interface Answer {
  question: string;
  answer: string;
  calls: { report: string; args: Record<string, string>; rows: unknown }[];
}

export interface MarketplaceClasses {
  available: boolean;
  /** `<publisher>|<offer>|<plan>` -> what Compass said it is. */
  classified: Record<string, { category: string; what: string; compass_alternative: boolean }>;
  products: number;
  pending: number;
}

const explainQuery = (kind: DrillKind, name: string, accounts: string[] | null) =>
  `kind=${kind}&name=${encodeURIComponent(name)}${accounts?.length ? `&accounts=${encodeURIComponent(accounts.join(','))}` : ''}`;
export const fetchExplain = (id: string, kind: DrillKind, name: string, accounts: string[] | null) =>
  apiFetch<Explanation>(`${customer(id)}/explain?${explainQuery(kind, name, accounts)}`);
/** What the seller told Compass about an item, kept with it. */
export interface ExplainNote {
  said: string;
  on: string;
}

export type Explanation = Kept<string> & { notes: ExplainNote[] };

/** `note`: the seller's answer to Compass's question, or what they know -- kept, and used from then on. */
export const writeExplain = (id: string, kind: DrillKind, name: string, accounts: string[] | null, note?: string) =>
  apiFetch<Explanation>(`${customer(id)}/explain?${explainQuery(kind, name, accounts)}`,
    { method: 'POST', body: JSON.stringify({ note: note ?? null }) });
export const fetchActions = () => apiFetch<Kept<NextAction[]>>(`${BASE}/advisor/actions`);
export const writeActions = () => apiFetch<Kept<NextAction[]>>(`${BASE}/advisor/actions`, { method: 'POST' });
/** A pitch Compass recommends: a catalog solution, the note's sizing, the playbook to use. */
export interface RecommendedPitch {
  pitch: string;
  solution_id: string;
  solution: string;
  play: string;
  why: string;
  playbook: string | null;
  confidence: 'high' | 'medium' | 'low';
  sized_monthly: number[] | null;
}

export const fetchPitches = (id: string) => apiFetch<Kept<RecommendedPitch[]>>(`${customer(id)}/pitches`);
export const writePitches = (id: string) => apiFetch<Kept<RecommendedPitch[]>>(`${customer(id)}/pitches`, { method: 'POST' });

export const draftFromPitch = (id: string, pitch: string) =>
  apiFetch<DraftOpportunity>(`${customer(id)}/draft`, { method: 'POST', body: JSON.stringify({ pitch }) });
export const sizeSolution = (solutionId: string, answers: string, customerId?: string) =>
  apiFetch<SizedSolution>(`${BASE}/solutions/${encodeURIComponent(solutionId)}/size`,
    { method: 'POST', body: JSON.stringify({ answers, customer: customerId ?? null }) });
export const askData = (question: string) =>
  apiFetch<Answer>(`${BASE}/ask`, { method: 'POST', body: JSON.stringify({ question }) });
export const fetchMarketplaceClasses = () => apiFetch<MarketplaceClasses>(`${BASE}/guide/marketplace`);
export const classifyMarketplace = () => apiFetch<MarketplaceClasses>(`${BASE}/guide/marketplace`, { method: 'POST' });

/** A new solution Compass proposed for subscriptions the rules could not place. */
export interface ProposedSolution {
  id: string;
  name: string;
  play: string | null;
  description: string;
  valid: boolean;
  problem: string | null;
  subscriptions: { key: string; subscription: string; customer: string }[];
  customers: string[];
  monthly: number;
}

export interface Placement {
  solution_id: string | null;
  solution: string | null;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  proposal: ProposedSolution | null;
  customer: string;
  subscription: string;
  monthly: number;
}

export interface Placements {
  available: boolean;
  /** `<customer id>|<subscription>` -> what Compass said. */
  suggestions: Record<string, Placement>;
  unplaced: number;
  pending: string[];
  proposals: ProposedSolution[];
}

const placementsQuery = (customerId?: string) => (customerId ? `?customer=${encodeURIComponent(customerId)}` : '');
export const fetchPlacements = (customerId?: string) => apiFetch<Placements>(`${BASE}/solutions/placements${placementsQuery(customerId)}`);
export const askPlacements = (customerId: string | undefined, limit: number) =>
  apiFetch<Placements>(`${BASE}/solutions/placements${placementsQuery(customerId)}${customerId ? '&' : '?'}limit=${limit}`,
    { method: 'POST' });
export const fetchProposalNote = (name: string) =>
  apiFetch<{ name: string; file: string; markdown: string }>(`${BASE}/solutions/proposals/note?name=${encodeURIComponent(name)}`);

/** The brief before a meeting, written by Compass (operator, 2026-10-23). */
export interface CustomerBrief {
  markdown?: string;
  generated_at?: string;
  fingerprint?: string;
  /** A brief is kept for this customer. */
  kept: boolean;
  /** The data has changed since it was written. */
  stale: boolean;
  /** Compass can be asked on this install. */
  available: boolean;
  facts: unknown;
}

/** One thing the seller told Compass about a customer (operator, 2026-10-23: "Brief me has no memory"). */
export interface MemoryLine {
  id: string;
  said: string;
  on: string;
  /** Where it was said: "you", "brief", or "explain: <kind> <name>". */
  source: string;
}

export const fetchMemory = (id: string) => apiFetch<MemoryLine[]>(`${customer(id)}/memory`);
export const remember = (id: string, said: string, source = 'you') =>
  apiFetch<MemoryLine[]>(`${customer(id)}/memory`, { method: 'POST', body: JSON.stringify({ said, source }) });
export const forget = (id: string, lineId: string) =>
  apiFetch<MemoryLine[]>(`${customer(id)}/memory/${encodeURIComponent(lineId)}`, { method: 'DELETE' });

export const fetchBrief = (id: string) => apiFetch<CustomerBrief>(`${customer(id)}/brief`);
export const writeBrief = (id: string) => apiFetch<CustomerBrief>(`${customer(id)}/brief`, { method: 'POST' });

export const fetchDrill = (id: string, kind: DrillKind, name: string, accounts: string[] | null) =>
  apiFetch<Drill>(`${customer(id)}/drill?kind=${kind}&name=${encodeURIComponent(name)}`
    + (accounts?.length ? `&accounts=${encodeURIComponent(accounts.join(','))}` : ''));

/** What a subscription looks like it is used for (operator, 2026-10-23). */
export interface FoundSolution {
  id: string;
  name: string;
  play: string;
  confidence: 'strong' | 'likely';
  evidence: { name: string; monthly: number | null }[];
  named: string[];
  primary: boolean;
}

export interface SubscriptionSolutions {
  subscription: string;
  monthly: number;
  environment: string | null;
  solutions: FoundSolution[];
  /** Fits, but too small a share of the subscription to be what it is for. */
  also: FoundSolution[];
  top_services: { name: string; monthly: number }[];
  resource_groups: string[];
}

/** A Solution note's template bill: building blocks at three sizes, USD a month. */
export interface SolutionSizing {
  rows: { block: string; service: string; small: number | null; medium: number | null; large: number | null; basis: string }[];
  totals: { small: number; medium: number; large: number };
}

/** What the vault's Solution note adds: where to read more, its sizing and its diagram. */
export interface SolutionGuide {
  id?: string;
  note?: string | null;
  sizing?: SolutionSizing | null;
  architecture?: string | null;
}

export interface SolutionSummary extends SolutionGuide {
  id: string;
  name: string;
  play: string;
  subscriptions: number;
  monthly: number;
}

export interface SolutionPitch {
  solution: string;
  play: string;
  pitch: string;
  subscriptions: string[];
}

export interface FootprintWindow {
  first_month: string | null;
  last_month: string | null;
  months: number;
  fetched_at: string | null;
}

export interface CustomerSolutions {
  customer: { id: string; name: string };
  window: FootprintWindow | null;
  synced: boolean;
  subscriptions: SubscriptionSolutions[];
  solutions: SolutionSummary[];
  pitches: SolutionPitch[];
  unclassified: { count: number; monthly: number };
}

export interface SolutionsAcross {
  window: FootprintWindow | null;
  by_solution: (Omit<SolutionSummary, 'subscriptions'> & { customers: string[]; subscriptions: number })[];
  customers: { id: string; name: string; monthly: number; subscriptions: number; solutions: string[]; pitches: number }[];
  pitches: (SolutionPitch & { customer: string; customer_id: string })[];
  subscriptions: (SubscriptionSolutions & { customer: string; customer_id: string })[];
  unclassified: (SubscriptionSolutions & { customer: string; customer_id: string })[];
}

export interface SolutionCatalog {
  patterns: unknown[];
  /** `vault`: from the Solution notes; `shipped`: the vault has none yet. */
  source: 'vault' | 'shipped';
  notes: { stem: string; name: string; id: string | null; status: string | null; error: string | null }[];
}

/** The Solutions Guide: playbooks, solutions and services, without choosing a customer. */
export interface GuideService {
  name: string;
  note: string | null;
  play: string | null;
  category?: string | null;
  customers: { id: string; name: string; monthly: number }[];
  monthly: number;
  solutions: { id: string; name: string; note?: string | null }[];
  /** For "SaaS" and "Azure Applications": the Marketplace products behind them, across customers. */
  marketplace?: { publisher: string; offer: string; plan: string; recurring?: boolean | null; monthly: number;
    customers: { id: string; name: string; monthly: number }[] }[];
}

export interface Guide {
  window: FootprintWindow | null;
  playbooks: { stem: string; name: string; play: string | null; status: string | null; solutions: string[]; summary: string }[];
  solutions: (SolutionGuide & { id: string; name: string; play: string; description?: string | null;
    customers: string[]; monthly: number })[];
  services: GuideService[];
}

export const fetchGuide = () => apiFetch<Guide>(`${BASE}/guide`);

export const fetchCustomerSolutions = (id: string, accounts?: string[]) =>
  apiFetch<CustomerSolutions>(`${customer(id)}/solutions${onlyAccounts(accounts)}`);
export const fetchSolutionsAcross = () => apiFetch<SolutionsAcross>(`${BASE}/solutions`);
export const fetchSolutionCatalog = () => apiFetch<SolutionCatalog>(`${BASE}/solutions/catalog`);

/** One baseline for every customer, the fiscal year, and the seller's quota. */
export interface QuotaSettings {
  fy_start_month: number;
  fy_first: string;
  fy_last: string;
  /** The quota's period: the one set (e.g. H2 2026), else the fiscal year (FY27). */
  fy: string;
  period_is_default: boolean;
  baseline_start: string;
  baseline_months: number;
  baseline_last: string;
  quota: number | null;
  baseline_is_default: boolean;
}

export interface QuotaOpportunity {
  id?: string; title: string; status: string; stage: string; route?: string; first_month: string; planned_to_date: number;
}

export interface QuotaPipeline {
  planned_to_date: number;
  achieved_to_date: number;
  gap: number;
  behind: boolean;
  opportunities: QuotaOpportunity[];
}

export interface CustomerQuota {
  customer: { id: string; name: string };
  settings: QuotaSettings;
  currency: string | null;
  baseline: number;
  baseline_covered: number;
  months: { month: string; kind: 'actual' | 'forecast'; consumption: number; baseline: number; above: number; pipeline: number }[];
  above_to_date: number;
  above_projected: number;
  above_with_pipeline: number;
  pipeline: QuotaPipeline;
  pipeline_available: boolean;
}

export interface QuotaAcross {
  settings: QuotaSettings;
  customers: {
    id: string; name: string; affiliates: number; currency: string | null; baseline: number; baseline_covered: number;
    above_to_date: number; above_projected: number; above_with_pipeline: number;
    pipeline: Omit<QuotaPipeline, 'opportunities'>; missed: QuotaOpportunity[];
  }[];
  above_to_date: number;
  above_projected: number;
  above_with_pipeline: number;
  attained_pct: number | null;
  projected_pct: number | null;
  with_pipeline_pct: number | null;
  gap_to_quota: number | null;
}

export const fetchQuota = (measure: Measure) => apiFetch<QuotaAcross>(`${BASE}/quota?${measureQuery(measure)}`);
export const fetchCustomerQuota = (id: string, measure: Measure, accounts?: string[]) =>
  apiFetch<CustomerQuota>(`${customer(id)}/quota?${measureQuery(measure)}${accountsQuery(accounts)}`);
export const saveQuotaSettings = (changes: Partial<{ quota: number | null; baseline_start: string | null;
  baseline_months: number; fy_start_month: number; period_first: string | null; period_last: string | null }>) =>
  apiFetch<QuotaSettings>(`${BASE}/quota/settings`, { method: 'PUT', body: JSON.stringify(changes) });

/** Every data file, zipped, to carry this plugin's data to another machine. */
export const dataExportPath = () => `${BASE}/data/export.zip`;

/** Replaces this machine's data with an export's. */
export const importData = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return apiFetch<{ files: number; customers: number; enrollments: number }>(`${BASE}/data/import`,
    { method: 'POST', body: form });
};

export const fetchWhitespace = () => apiFetch<WhitespaceRow[]>(`${BASE}/whitespace`);

export const fetchGrowth = () => apiFetch<GrowthRow[]>(`${BASE}/growth`);

export const fetchSolutionPlays = () => apiFetch<SolutionPlaysSettings>(`${BASE}/solution-plays`);

/** `play` null puts the service back to its default play. */
export const setSolutionPlay = (service: string, play: string | null) =>
  apiFetch<SolutionPlaysSettings>(`${BASE}/solution-plays`, { method: 'PUT', body: JSON.stringify({ service, play }) });

export const fetchSyncStatus = () => apiFetch<SyncStatus>(`${BASE}/sync`);

export const fetchSyncLog = () => apiFetch<{ runs: (SyncRun & { events: number })[] }>(`${BASE}/sync/log`);

/** One run and its newest events; `latest` for the newest run. */
export const fetchSyncRun = (runId: string, last = 200) =>
  apiFetch<SyncRun & { events: SyncEvent[] }>(`${BASE}/sync/log/${encodeURIComponent(runId)}?last=${last}`);

/** `profiles`: also sync every other billing profile lightly ('also'), or only them ('only'). */
export const startSync = (customerId?: string, profiles: 'none' | 'also' | 'only' = 'none') => {
  const query = [customerId ? `customer=${encodeURIComponent(customerId)}` : '', profiles !== 'none' ? `profiles=${profiles}` : '']
    .filter(Boolean).join('&');
  return apiFetch<SyncStatus>(`${BASE}/sync${query ? `?${query}` : ''}`, { method: 'POST' });
};
