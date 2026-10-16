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
  tracked?: boolean;
}

export interface TrackedAccount extends BillingAccount {
  customer: string | null;
  fetched_at: string | null;
  stale: boolean;
}

export interface MonthTotal {
  month: string;
  actual: number;
  amortized: number;
  mom_pct: number | null;
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

export interface Commitment {
  kind: 'macc' | 'ea-prepayment';
  currency: string | null;
  original: number;
  consumed: number;
  remaining: number;
  consumed_pct: number | null;
  start: string | null;
  end: string | null;
  run_rate: number | null;
  projected_exhaustion: string | null;
  projected_shortfall: number | null;
  verdict: string | null;
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

export interface Analysis {
  account: TrackedAccount;
  fetched_at: string | null;
  stale: boolean;
  errors: Record<string, string>;
  currency: string | null;
  months: MonthTotal[];
  last_closed_month: string;
  top_services: Breakdown;
  subscriptions: Breakdown;
  anomalies: Anomaly[];
  commitment: Commitment | null;
  forecast: Forecast;
}

export interface ConsumptionRow {
  month: string;
  service?: string;
  subscription?: string;
  cost: number;
}

const tracked = (name: string) => `${BASE}/tracked/${encodeURIComponent(name)}`;

export const fetchSignIn = () => apiFetch<SignInState>(`${BASE}/sign-in`);

export const fetchBillingAccounts = () => apiFetch<BillingAccount[]>(`${BASE}/billing-accounts`);

export const fetchTracked = () => apiFetch<TrackedAccount[]>(`${BASE}/tracked`);

export const saveTracked = (accountNames: string[]) =>
  apiFetch<TrackedAccount[]>(`${BASE}/tracked`, {
    method: 'PUT',
    body: JSON.stringify({ account_names: accountNames }),
  });

export const fetchAnalysis = (name: string) => apiFetch<Analysis>(`${tracked(name)}/analysis`);

export const refreshAccount = (name: string) =>
  apiFetch<Analysis>(`${tracked(name)}/refresh`, { method: 'POST' });

export const fetchConsumption = (name: string, group: 'service' | 'subscription') =>
  apiFetch<{ rows: ConsumptionRow[] }>(`${tracked(name)}/consumption?group=${group}&cost=actual`);
