import { useEffect, useState } from 'react';
import { useUrlState } from '../../pluginHost/state';
import { SeriesChart } from './charts';
import { fetchTags, startTagSync, UNTAGGED, type TagsReport, type View } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

// Values beyond these are added up as "Other" in the chart; the table lists them all.
const CHARTED_VALUES = 6;

/** A customer's cost by business tag: each dimension's values by month, how much
 *  of the spend carries the tag at all, and the spellings behind it. */
export function TagsTab({ customerId, syncedVersion, view, accounts }: {
  customerId: string; syncedVersion: number; view: View; accounts?: string[];
}) {
  const [report, setReport] = useState<TagsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [chosen, setChosen] = useUrlState<string>('dimension', '');

  useEffect(() => {
    fetchTags(customerId, accounts).then((result) => { setReport(result); setError(null); },
      (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, syncedVersion, accounts?.join(',')]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!report) return <Loading />;

  const syncTags = view === 'account' ? (
    <button type="button" className="btn" onClick={() => startTagSync(customerId).then(
      (status) => setNotice(status.started ? 'Tag sync started; the page fills in as it runs.' : 'A sync is already running.'),
      (failure) => setNotice(errorText(failure)))}>Sync tags</button>
  ) : null;

  if (!report.dimensions.length) {
    return (
      <>
        <p className="empty-state">
          {report.synced ? 'None of the usual business tags (environment, project, application, business unit, owner, cost centre) is used on these enrollments.'
            : 'Tags not synced for this customer yet.'}
        </p>
        <div className="azure-cost-toolbar">{syncTags}</div>
        {notice ? <p className="text-muted azure-cost-note">{notice}</p> : null}
      </>
    );
  }

  const currency = report.currency;
  const dimension = report.dimensions.find((item) => item.dimension === chosen) ?? report.dimensions[0];
  const months = Object.keys(dimension.months).sort();
  const totals: Record<string, number> = {};
  for (const values of Object.values(dimension.months)) {
    for (const [name, cost] of Object.entries(values)) totals[name] = (totals[name] ?? 0) + cost;
  }
  const ranked = Object.entries(totals).filter(([name]) => name !== UNTAGGED).sort((a, b) => b[1] - a[1]);
  const charted = ranked.slice(0, CHARTED_VALUES).map(([name]) => name);
  const last = dimension.last_month ? dimension.months[dimension.last_month] ?? {} : {};

  return (
    <>
      <div className="azure-cost-toolbar">
        <div className="azure-cost-segmented" role="tablist" aria-label="Tag">
          {report.dimensions.map((item) => (
            <button key={item.dimension} type="button" role="tab" aria-selected={item === dimension}
                    className={item === dimension ? 'active' : undefined} onClick={() => setChosen(item.dimension)}>
              {item.dimension}
            </button>
          ))}
        </div>
        {syncTags}
      </div>
      {notice ? <p className="text-muted azure-cost-note">{notice}</p> : null}

      <div className="azure-cost-kpis">
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Tagged with {dimension.dimension}</span>
          <strong>{dimension.coverage_pct == null ? '—' : `${dimension.coverage_pct}%`}</strong>
          <span className="azure-cost-kpi-detail">{dimension.last_month ? `of ${formatMonth(dimension.last_month)}'s spend` : 'no closed month yet'}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Untagged</span>
          <strong>{formatMoney(last[UNTAGGED] ?? 0, currency)}</strong>
          <span className="azure-cost-kpi-detail">{dimension.last_month ? formatMonth(dimension.last_month) : ''}</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Values</span>
          <strong>{dimension.values}</strong>
          <span className="azure-cost-kpi-detail">after folding case and synonyms</span></div>
        <div className="azure-cost-kpi card"><span className="azure-cost-kpi-label">Spellings of the key</span>
          <strong>{dimension.all_spellings.length}</strong>
          <span className="azure-cost-kpi-detail">among {report.tag_keys} tag keys</span></div>
      </div>

      {months.length ? (
        <section className="card azure-cost-card">
          <h3>{dimension.dimension} by month</h3>
          <SeriesChart label={`${dimension.dimension} by month`} currency={currency} height={300}
                       categories={months} categoryLabel={(month) => formatMonth(month, true)}
                       series={[
                         ...charted.map((name, index) => ({ name, data: months.map((month) => dimension.months[month][name] ?? null), stack: 't', color: index })),
                         { name: 'Other', data: months.map((month) => Object.entries(dimension.months[month])
                           .filter(([name]) => name !== UNTAGGED && !charted.includes(name)).reduce((sum, [, cost]) => sum + cost, 0) || null),
                         stack: 't', color: 'other' as const },
                         { name: 'Untagged', data: months.map((month) => dimension.months[month][UNTAGGED] ?? null), stack: 't', color: 'other' as const },
                       ]} />
          <table className="azure-cost-table">
            <thead><tr><th>{dimension.dimension}</th>{months.map((month) => <th key={month}>{formatMonth(month, true)}</th>)}<th>Total</th></tr></thead>
            <tbody>
              {[...ranked, ...(totals[UNTAGGED] ? [[UNTAGGED, totals[UNTAGGED]] as [string, number]] : [])].map(([name, total]) => (
                <tr key={name}>
                  <td>{name === UNTAGGED ? <em>Untagged</em> : name}</td>
                  {months.map((month) => <td key={month}>{dimension.months[month][name] ? formatMoney(dimension.months[month][name], currency, true) : '—'}</td>)}
                  <td>{formatMoney(total, currency, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : <p className="text-muted">The {dimension.dimension} tag is on these enrollments; its costs arrive with the next tag sync.</p>}

      <section className="card azure-cost-card">
        <h3>Tag hygiene: how {dimension.dimension} is spelled</h3>
        <p className="text-muted azure-cost-note">
          Every tag key on these enrollments that spells {dimension.dimension}. Costs are read under the first four;
          one spelling across the estate would make this report exact and untagged spend easier to chase.
        </p>
        <p>{dimension.all_spellings.map((key) => (
          <code key={key} className={dimension.spellings.includes(key) ? 'azure-cost-tag-key used' : 'azure-cost-tag-key'}>{key}</code>
        ))}</p>
        <p className="text-muted azure-cost-note">
          Untagged is the month's total less what any spelling tagged — exact for one spelling, close for several.
        </p>
      </section>
    </>
  );
}
