import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { apiUrl } from '../../pluginHost/api';
import { createOpportunity, fetchWhitespace, type WhitespaceRow, reportExportPath } from './client';
import { PopupRow } from './Popup';
import { errorText, formatMoney } from './format';
import { reportLink } from './ReportsHome';

const PREVIEWED = 3;

function Propose({ row, gap }: { row: WhitespaceRow; gap: WhitespaceRow['gaps'][number] }) {
  const [state, setState] = useState<'idle' | 'saving' | 'done'>('idle');
  const [error, setError] = useState<string | null>(null);
  if (!row.entity_customer) return <span className="text-muted" title="Link this customer to its note in Settings">—</span>;
  if (state === 'done') return <span className="text-muted">Opportunity created</span>;
  // No consumption plan: a gap is a lead, not a forecast.
  const title = `${row.name} – adopt ${gap.service} (${gap.play})`;
  return (
    <>
      <button type="button" className="btn" disabled={state === 'saving'} onClick={() => {
        setState('saving');
        createOpportunity(row.id, row.entity_customer!, title, { status: 'Open', stage: 'Identified' }, [])
          .then(() => setState('done'), (failure) => { setState('idle'); setError(errorText(failure)); });
      }}>{state === 'saving' ? 'Creating…' : 'Create opportunity'}</button>
      {error ? <div className="azure-cost-error">{error}</div> : null}
    </>
  );
}

/** The services most other customers use and each customer does not (operator,
 *  2026-10-21) -- by solution play, with what a typical user spends a month. */
export function WhitespacePage() {
  const [rows, setRows] = useState<WhitespaceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [play, setPlay] = useState<string>('All');

  useEffect(() => {
    fetchWhitespace().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  const plays = useMemo(() => ['All', ...new Set((rows ?? []).flatMap((row) => row.gaps.map((gap) => gap.play)))], [rows]);
  const gapsOf = (row: WhitespaceRow) => row.gaps.filter((gap) => play === 'All' || gap.play === play);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Service whitespace' }]} />
      <header className="azure-cost-header">
        <h1>Service whitespace</h1>
        <a className="btn azure-cost-settings-link" href={apiUrl(reportExportPath('whitespace'))}>Export to Excel</a>
      </header>
      <p className="text-muted azure-cost-note">
        A customer uses a service when it spent $500 a month or more on it over its last three closed months. A gap is
        a service at least 30% of customers (and three or more) use that this one does not. Groups include their
        affiliates; Marketplace and Unassigned spend are left out.
      </p>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <section className="card azure-cost-card">
          <div className="azure-cost-chips" role="group" aria-label="Solution play">
            {plays.map((name) => (
              <button key={name} type="button" className={play === name ? 'active' : undefined}
                      aria-pressed={play === name} onClick={() => setPlay(name)}>{name}</button>
            ))}
          </div>
          <table className="azure-cost-table">
            <thead><tr><th>Customer</th><th>Services used</th><th>Gaps</th><th>Most common gaps</th></tr></thead>
            <tbody>
              {rows.filter((row) => gapsOf(row).length).map((row) => (
                <Fragment key={row.id}>
                  <tr>
                    <td>
                      <button type="button" className="btn azure-cost-link-button" aria-expanded={open === row.id}
                              onClick={() => setOpen(open === row.id ? null : row.id)}>{open === row.id ? '▾' : '▸'}</button>{' '}
                      <Link to={reportLink('Breakdown', row.id)}>{row.name}</Link>
                    </td>
                    <td>{row.uses}</td>
                    <td>{gapsOf(row).length}</td>
                    <td>{gapsOf(row).slice(0, PREVIEWED).map((gap) => gap.service).join(' · ')}</td>
                  </tr>
                  {open === row.id ? (
                    <PopupRow kicker="Service whitespace" title={row.name} onClose={() => setOpen(null)}>
                        <table className="azure-cost-table">
                          <thead><tr><th>Service</th><th>Solution play</th><th>Customers using it</th>
                            <th>Typical spend a month</th><th /></tr></thead>
                          <tbody>
                            {gapsOf(row).map((gap) => (
                              <tr key={gap.service}>
                                <td>{gap.service}</td><td>{gap.play}</td>
                                <td>{gap.users} ({gap.adoption_pct}%)</td>
                                <td>{formatMoney(gap.typical_monthly, row.currency, true)}</td>
                                <td><Propose row={row} gap={gap} /></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </PopupRow>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
