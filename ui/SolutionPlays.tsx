import { useEffect, useMemo, useState } from 'react';
import { SeriesChart } from './charts';
import { fetchSolutionPlays, setSolutionPlay, type Analysis, type SolutionPlaysSettings } from './client';
import { DrillLink, useDrillOpener } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';

const SHOWN_MONTHS = 12;

/** A customer's spend by solution play (operator, 2026-10-21): the last twelve
 *  months stacked, and the last closed month against the one before. */
export function SolutionPlaysCard({ analysis }: { analysis: Analysis }) {
  const drill = useDrillOpener();
  const months = (analysis.solution_plays ?? []).slice(-SHOWN_MONTHS);
  if (!months.length) return null;
  const currency = analysis.currency;
  const plays = [...new Set(months.flatMap((row) => Object.keys(row.by_play)))];
  const closedAt = months.findIndex((row) => row.month === analysis.last_closed_month);
  const latest = closedAt >= 0 ? months[closedAt] : null;
  const before = closedAt > 0 ? months[closedAt - 1] : null;
  const total = latest ? Object.values(latest.by_play).reduce((sum, cost) => sum + cost, 0) : 0;
  const ranked = latest ? Object.entries(latest.by_play).sort((a, b) => b[1] - a[1]) : [];
  return (
    <section className="card azure-cost-card azure-cost-wide">
      <h3>By solution play</h3>
      <SeriesChart label="Spend by solution play" currency={currency} height={300}
                   categories={months.map((row) => row.month)} categoryLabel={(month) => formatMonth(month, true)}
                   onPick={drill ? (month, play) => (play ? drill('play', play) : drill('month', month)) : undefined}
                   series={plays.map((play, index) => ({ name: play, stack: 'plays', color: index,
                     data: months.map((row) => row.by_play[play] ?? 0) }))} />
      {latest ? (
        <table className="azure-cost-table">
          <thead><tr><th>{formatMonth(latest.month)}</th><th>Spend</th><th>Share</th><th>Against the month before</th></tr></thead>
          <tbody>
            {ranked.map(([play, cost]) => {
              const previous = before?.by_play[play] ?? 0;
              const change = cost - previous;
              return (
                <tr key={play}>
                  <td><DrillLink kind="play" name={play} /></td>
                  <td>{formatMoney(cost, currency)}</td>
                  <td>{total ? `${Math.round((cost / total) * 1000) / 10}%` : '—'}</td>
                  <td>{before ? `${change >= 0 ? '+' : '−'}${formatMoney(Math.abs(change), currency)}` : '—'}
                    {before && previous ? <span className="text-muted"> ({change >= 0 ? '+' : ''}{Math.round((change / previous) * 1000) / 10}%)</span> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      <p className="text-muted azure-cost-note">
        Cost Management's actual cost by service, each service in its play (Settings); GPU virtual machines count as AI &amp; ML.
      </p>
    </section>
  );
}

/** Which play each service belongs to: the defaults, changed one service at a time. */
export function SolutionPlaysSettingsCard() {
  const [view, setView] = useState<SolutionPlaysSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [onlyUnmapped, setOnlyUnmapped] = useState(false);

  useEffect(() => {
    fetchSolutionPlays().then(setView, (failure) => setError(errorText(failure)));
  }, []);

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (view?.services ?? []).filter((row) => (!needle || row.service.toLowerCase().includes(needle)
      || row.play.toLowerCase().includes(needle)) && (!onlyUnmapped || view?.unmapped.includes(row.service)));
  }, [view, search, onlyUnmapped]);

  function change(service: string, play: string | null) {
    setSolutionPlay(service, play).then((next) => { setView(next); setError(null); },
      (failure) => setError(errorText(failure)));
  }

  return (
    <section className="card azure-cost-card">
      <h3>Solution plays</h3>
      <p className="text-muted azure-cost-note">
        Each Azure service counts toward one play. {view?.gpu_rule}
        {view?.unmapped.length ? ` ${view.unmapped.length} service(s) are in no play yet and count as Unassigned.` : ''}
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!view ? <p className="text-muted">Loading…</p> : (
        <>
          <div className="azure-cost-toolbar">
            <input type="search" placeholder={`Search ${view.services.length} services or plays`} value={search}
                   onChange={(event) => setSearch(event.target.value)} />
            {view.unmapped.length ? (
              <label className="azure-cost-check">
                <input type="checkbox" checked={onlyUnmapped} onChange={(event) => setOnlyUnmapped(event.target.checked)} />
                Only the ones in no play
              </label>
            ) : null}
          </div>
          <table className="azure-cost-table">
            <thead><tr><th>Service</th><th>Spend, all synced months</th><th>Solution play</th><th /></tr></thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.service}>
                  <td>{row.service}</td>
                  <td>{formatMoney(row.spend, 'USD', true)}</td>
                  <td>
                    <select value={row.play} onChange={(event) => change(row.service, event.target.value)}>
                      {view.plays.map((play) => <option key={play} value={play}>{play}</option>)}
                    </select>
                  </td>
                  <td>
                    {row.changed ? (
                      <button type="button" className="btn azure-cost-link-button" onClick={() => change(row.service, null)}
                              title={`Back to ${row.default ?? 'Unassigned'}`}>Reset</button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
