import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { fetchTagsAcross, startTagSync, type TagsAcrossRow } from './client';
import { errorText } from './format';
import { reportLink } from './ReportsHome';

const DIMENSIONS = ['Environment', 'Project', 'Application', 'Business unit', 'Owner', 'Cost centre'];

/** How much of each customer's spend carries each business tag -- where showback
 *  works, and where a tagging conversation comes first. */
export function TagCoveragePage() {
  const [rows, setRows] = useState<TagsAcrossRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    fetchTagsAcross().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Tag coverage' }]} />
      <header className="azure-cost-header">
        <h1>Tag coverage</h1>
        <button type="button" className="btn azure-cost-settings-link" onClick={() => startTagSync().then(
          (status) => setNotice(status.started ? 'Tag sync started for every customer.' : 'A sync is already running.'),
          (failure) => setNotice(errorText(failure)))}>Sync tags</button>
      </header>
      <p className="text-muted azure-cost-note">
        The share of each customer's last closed month carrying each business tag, under any of its spellings. In
        brackets, how many spellings of the key the customer uses. Groups include their affiliates.
      </p>
      {notice ? <p className="text-muted azure-cost-note">{notice}</p> : null}
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!rows ? <p className="text-muted">Loading…</p> : (
        <section className="card azure-cost-card">
          <table className="azure-cost-table">
            <thead><tr><th>Customer</th><th>Tag keys</th>{DIMENSIONS.map((name) => <th key={name}>{name}</th>)}</tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td><Link to={reportLink('Tags', row.id)}>{row.name}</Link></td>
                  {row.synced ? (
                    <>
                      <td>{row.tag_keys}</td>
                      {DIMENSIONS.map((name) => (
                        <td key={name}>
                          {row.coverage[name] != null ? `${row.coverage[name]}%` : row.spellings[name] ? 'syncing' : '—'}
                          {row.spellings[name] > 1 ? <span className="text-muted"> ({row.spellings[name]})</span> : null}
                        </td>
                      ))}
                    </>
                  ) : <td colSpan={DIMENSIONS.length + 1} className="text-muted">Tags not synced yet</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
