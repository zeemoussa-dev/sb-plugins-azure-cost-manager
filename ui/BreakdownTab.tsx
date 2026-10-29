import { useEffect, useState } from 'react';
import { ChangeBars, RankedBars, SeriesChart, StackedMonthsChart } from './charts';
import { fetchConsumption, type Analysis, type ConsumptionRow, type MixGroup } from './client';
import { DrillLink, useDrillOpener } from './Drill';
import { formatMoney, formatMonth } from './format';
import { SubscriptionGroups } from './SubscriptionGroups';
import { SubscriptionLabel } from './SubscriptionLabel';

const MIX_LABELS: Record<MixGroup, string> = {
  service: 'Services', play: 'Solution plays', subscription: 'Subscriptions', account: 'Enrollments',
};

function AnomalyList({ analysis }: { analysis: Analysis }) {
  const label = { spike: 'Spike', drop: 'Drop', new: 'New' } as const;
  return (
    <section className="card azure-cost-card">
      <h3>Anomalies in {formatMonth(analysis.last_closed_month)}</h3>
      {analysis.anomalies.length === 0 ? (
        <p className="text-muted">Nothing moved sharply against its last three months.</p>
      ) : (
        <>
        <ChangeBars label="Change against the 3-month baseline" currency={analysis.currency}
                    rows={analysis.anomalies.map((anomaly) => ({ name: anomaly.service, change: anomaly.change }))} />
        <table className="azure-cost-table">
          <thead><tr><th>Service</th><th>Kind</th><th>Month</th><th>3-month baseline</th><th>Change</th></tr></thead>
          <tbody>
            {analysis.anomalies.map((anomaly) => (
              <tr key={anomaly.service}>
                <td><DrillLink kind="service" name={anomaly.service} /></td>
                <td><span className={`azure-cost-anomaly ${anomaly.kind}`}>{label[anomaly.kind]}</span></td>
                <td>{formatMoney(anomaly.cost, analysis.currency)}</td>
                <td>{formatMoney(anomaly.baseline, analysis.currency)}</td>
                <td>{anomaly.change > 0 ? '+' : ''}{formatMoney(anomaly.change, analysis.currency)}
                  {anomaly.change_pct != null ? ` (${anomaly.change_pct > 0 ? '+' : ''}${anomaly.change_pct}%)` : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </>
      )}
    </section>
  );
}

/** GPU by SKU and Azure OpenAI PTU against tokens, each by how it was bought. */
function GpuAndAi({ analysis }: { analysis: Analysis }) {
  const drill = useDrillOpener();
  const monthsWithLines = analysis.gpu_and_ai;
  const keys = [...new Set(monthsWithLines.flatMap((row) => row.lines.map((line) => `${line.category} · ${line.pricing}`)))].sort();
  const latest = [...monthsWithLines].reverse().find((row) => row.lines.length);
  if (!keys.length) {
    return (
      <section className="card azure-cost-card">
        <h3>GPU &amp; AI</h3>
        <p className="text-muted">No GPU or Azure OpenAI spend in the synced months.</p>
      </section>
    );
  }
  return (
    <section className="card azure-cost-card">
      <h3>GPU &amp; AI</h3>
      <SeriesChart label="GPU and AI by month" currency={analysis.currency} height={320} onPick={drill ? (month) => drill('month', month) : undefined}
                   categories={monthsWithLines.map((row) => row.month)} categoryLabel={(m) => formatMonth(m, true)}
                   series={keys.map((key, index) => ({ name: key, stack: 'ai', color: index,
                     data: monthsWithLines.map((row) => row.lines.filter((line) => `${line.category} · ${line.pricing}` === key)
                       .reduce((sum, line) => sum + line.cost, 0)) }))} />
      {latest ? (
        <table className="azure-cost-table">
          <thead><tr><th>{formatMonth(latest.month)}</th><th>Bought as</th><th>Cost</th></tr></thead>
          <tbody>
            {latest.lines.map((line) => (
              <tr key={`${line.category}-${line.pricing}`}><td>{line.category}</td><td>{line.pricing}</td>
                <td>{formatMoney(line.cost, analysis.currency)}</td></tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

export function BreakdownTab({ analysis, syncedVersion }: { analysis: Analysis; syncedVersion: number }) {
  const [mix, setMix] = useState<ConsumptionRow[]>([]);
  const [mixBy, setMixBy] = useState<MixGroup>('service');
  const drill = useDrillOpener();
  // A bar of the mix opens what it is (an enrollment or "Other" opens its month instead).
  const pickMix = drill ? (month: string, series: string) => {
    if (series && series !== 'Other' && mixBy !== 'account') drill(mixBy, series);
    else drill('month', month);
  } : undefined;
  const customerId = analysis.customer.id;
  // The report's Enrollments choice: some of the group's, or all of them.
  const shown = analysis.shown_accounts && analysis.shown_accounts.length < analysis.group.accounts.length
    ? analysis.shown_accounts : undefined;
  const shownKey = shown?.join(',') ?? '';

  useEffect(() => {
    fetchConsumption(customerId, mixBy, shownKey ? shownKey.split(',') : undefined)
      .then((result) => setMix(result.rows), () => setMix([]));
  }, [customerId, mixBy, syncedVersion, shownKey]);

  return (
    <>
      <GpuAndAi analysis={analysis} />
      <section className="card azure-cost-card">
        <div className="azure-cost-card-head">
          <h3>Spend by month</h3>
          <div className="azure-cost-segmented">
            {(Object.keys(MIX_LABELS) as MixGroup[]).map((group) => (
              <button key={group} type="button" className={group === mixBy ? 'active' : undefined} onClick={() => setMixBy(group)}>
                {MIX_LABELS[group]}
              </button>
            ))}
          </div>
        </div>
        <StackedMonthsChart rows={mix} groupKey={mixBy} currency={analysis.currency} onPick={pickMix} />
        <p className="text-muted azure-cost-note">Cost Management's actual cost: Marketplace included, credits not subtracted.</p>
      </section>
      <div className="azure-cost-columns">
        <section className="card azure-cost-card">
          <h3>Top services, {formatMonth(analysis.top_services.month)}</h3>
          <RankedBars rows={analysis.top_services.rows} currency={analysis.currency}
                      onPick={drill ? (name) => drill('service', name) : undefined} />
          {analysis.top_services.others ? (
            <p className="text-muted azure-cost-note">All other services: {formatMoney(analysis.top_services.others, analysis.currency)}</p>
          ) : null}
        </section>
        <section className="card azure-cost-card">
          <h3>Subscriptions, {formatMonth(analysis.subscriptions.month)}</h3>
          <RankedBars rows={analysis.subscriptions.rows.slice(0, 10)} currency={analysis.currency}
                      onPick={drill ? (name) => drill('subscription', name) : undefined}
                      renderName={(name) => <SubscriptionLabel name={name} />} />
        </section>
      </div>
      <SubscriptionGroups customerId={customerId} accounts={shown} syncedVersion={syncedVersion} />
      <AnomalyList analysis={analysis} />
    </>
  );
}
