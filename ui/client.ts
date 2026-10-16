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
}

export interface CustomerDraft {
  name: string;
  accounts: string[];
  commitment: Partial<Commitment> | null;
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

export interface Analysis {
  customer: Customer;
  synced_at: string | null;
  stale: boolean;
  errors: Record<string, Record<string, string>>;
  currency: string | null;
  months: MonthTotal[];
  last_closed_month: string;
  top_services: Breakdown;
  subscriptions: Breakdown;
  enrollments: Breakdown;
  anomalies: Anomaly[];
  commitment: BurnDown | null;
  forecast: Forecast;
}

export interface ConsumptionRow {
  month: string;
  name: string;
  cost: number;
}

export type MixGroup = 'service' | 'subscription' | 'account';

export interface SyncStatus {
  running: boolean;
  started_at: string | null;
  finished_at: string | null;
  scope: string | null;
  current: { account: string; first_month: string; last_month: string; waiting_seconds?: number } | null;
  accounts_done: number;
  accounts_total: number;
  errors: { account: string | null; message: string }[];
  started?: boolean;
  reason?: string;
}

const customer = (id: string) => `${BASE}/customers/${encodeURIComponent(id)}`;

export const fetchSignIn = () => apiFetch<SignInState>(`${BASE}/sign-in`);

export const fetchBillingAccounts = (fresh = false) =>
  apiFetch<BillingAccount[]>(`${BASE}/billing-accounts${fresh ? '?fresh=true' : ''}`);

export const fetchCommitmentTypes = () => apiFetch<string[]>(`${BASE}/commitment-types`);

export const fetchCustomers = () => apiFetch<Customer[]>(`${BASE}/customers`);

export const saveCustomer = (id: string | null, draft: CustomerDraft) =>
  apiFetch<Customer>(id ? customer(id) : `${BASE}/customers`, {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(draft),
  });

export const deleteCustomer = (id: string) => apiFetch<{ deleted: string }>(customer(id), { method: 'DELETE' });

export const fetchAnalysis = (id: string) => apiFetch<Analysis>(`${customer(id)}/analysis`);

export const fetchConsumption = (id: string, group: MixGroup) =>
  apiFetch<{ rows: ConsumptionRow[] }>(`${customer(id)}/consumption?group=${group}&cost=actual`);

export const fetchSyncStatus = () => apiFetch<SyncStatus>(`${BASE}/sync`);

export const startSync = (customerId?: string) =>
  apiFetch<SyncStatus>(`${BASE}/sync${customerId ? `?customer=${encodeURIComponent(customerId)}` : ''}`,
    { method: 'POST' });
