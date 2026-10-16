import { ApiError } from '../../pluginHost/api';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function formatMonth(month: string, short = false): string {
  const [year, number] = month.split('-');
  const name = MONTHS[Number(number) - 1] ?? month;
  return short ? `${name} ${year.slice(2)}` : `${name} ${year}`;
}

export function formatMoney(value: number, currency: string | null, compact = false): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: currency ? 'currency' : 'decimal',
      currency: currency ?? undefined,
      notation: compact ? 'compact' : 'standard',
      maximumFractionDigits: compact ? 1 : 0,
    }).format(value);
  } catch {
    return `${Math.round(value).toLocaleString()}${currency ? ` ${currency}` : ''}`;
  }
}

/** The backend's `detail`, rather than the raw JSON the host's ApiError carries. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const detail = JSON.parse(error.message).detail;
      if (typeof detail === 'string') return detail;
    } catch {
      // not JSON: fall through to the raw text
    }
    return error.message || `Request failed (${error.status})`;
  }
  return error instanceof Error ? error.message : String(error);
}

export function agreementLabel(agreementType: string): string {
  if (agreementType === 'EnterpriseAgreement') return 'EA';
  if (agreementType === 'MicrosoftCustomerAgreement') return 'MCA';
  if (agreementType === 'MicrosoftPartnerAgreement') return 'MPA';
  return agreementType;
}
