import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useRememberedState, useUrlFilters } from '../../pluginHost/state';
import { fetchPortfolio, type PortfolioRow, type PortfolioStatus } from './client';
import { errorText, formatMoney, formatMonth } from './format';
import { reportLink, reportTitle, settingsLink, type Report } from './ReportsHome';

const STATUS_LABELS: Record<PortfolioStatus, string> = {
  behind: 'Behind',
  early: 'Exhausts early',
  'on-track': 'On track',
  consumed: 'Consumed',
  'no-macc': 'No MACC set',
  'parent-macc': "In parent's MACC",
  'not-synced': 'Not synced',
};
// Worst first, so sorting by status puts what needs attention on top.
const STATUS_ORDER: PortfolioStatus[] = ['behind', 'early', 'on-track', 'consumed', 'no-macc', 'parent-macc', 'not-synced'];

const FILTERS = ['all', 'behind', 'early', 'no-macc', 'not-synced', 'groups', 'standalone'] as const;
type Filter = typeof FILTERS[number];
const FILTER_LABELS: Record<Filter, string> = {
  all: 'All', behind: 'Behind', early: 'Exhausts early', 'no-macc': 'No MACC set', 'not-synced': 'Not synced',
  groups: 'Groups', standalone: 'Standalone',
};

const SORTS = ['name', 'signed', 'burn', 'last', 'trend', 'status'] as const;
type Sort = typeof SORTS[number];

function sortValue(row: PortfolioRow, sort: Sort): number | string {
  switch (sort) {
    case 'name': return row.name.toLowerCase();
    case 'signed': return row.signed ?? -1;
    case 'burn': return row.burn ? row.burn.consumed_pct - row.burn.elapsed_pct : -Infinity;
    case 'last': return row.last_month?.actual ?? -1;
    case 'trend': return row.last_month?.mom_pct ?? -Infinity;
    case 'status': return STATUS_ORDER.indexOf(row.status);
  }
}

function compare(sort: Sort, descending: boolean) {
  return (a: PortfolioRow, b: PortfolioRow) => {
    const left = sortValue(a, sort);
    const right = sortValue(b, sort);
    const order = left < right ? -1 : left > right ? 1 : a.name.localeCompare(b.name);
    return descending ? -order : order;
  };
}

function Sparkline({ points }: { points: { actual: number }[] }) {
  if (points.length < 2) return null;
  const values = points.map((point) => point.actual);
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  const path = values.map((value, index) =>
    `${(index / (values.length - 1)) * 80},${20 - ((value - low) / span) * 18 - 1}`).join(' ');
  return (
    <svg className="azure-cost-sparkline" viewBox="0 0 80 20" width="80" height="20" aria-hidden="true">
      <polyline points={path} fill="none" strokeWidth="1.5" />
    </svg>
  );
}

function BurnCell({ row }: { row: PortfolioRow }) {
  if (!row.burn) {
    return row.allocated ? <span className="text-muted">{formatMoney(row.allocated, row.currency, true)} allocated to affiliates</span>
      : <span className="text-muted">—</span>;
  }
  const { consumed_pct: consumed, elapsed_pct: elapsed } = row.burn;
  return (
    <div className="azure-cost-burn" title={`${consumed}% consumed, ${elapsed}% of the term elapsed`}>
      <div className="azure-cost-burn-track">
        <div className={`azure-cost-burn-fill ${consumed >= elapsed ? 'ahead' : 'behind'}`}
             style={{ width: `${Math.min(consumed, 100)}%` }} />
        <div className="azure-cost-burn-marker" style={{ left: `${Math.min(elapsed, 100)}%` }} />
      </div>
      <span className="text-muted">{consumed}% · term {elapsed}%</span>
    </div>
  );
}

function projectedText(row: PortfolioRow): string {
  if (!row.burn) return '—';
  if (row.burn.remaining <= 0) return 'Consumed';
  if (row.burn.projected_exhaustion) return `Exhausts ${formatMonth(row.burn.projected_exhaustion)}`;
  if (row.burn.projected_shortfall > 0) return `${formatMoney(row.burn.projected_shortfall, row.currency, true)} short at term end`;
  return 'Consumed by term end';
}

function syncedText(syncedAt: string): string {
  return new Date(syncedAt).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

/** Every customer at a glance, each group's affiliates folded under it; a row opens the report. */
export function CustomerPortfolio({ report }: { report: Report }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [rows, setRows] = useState<PortfolioRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilter] = useUrlFilters({ search: '', show: 'all', sort: 'status' });
  const [expanded, setExpanded] = useRememberedState<string[]>('azure-cost-manager.expanded-groups', []);

  useEffect(() => {
    fetchPortfolio().then(setRows, (failure) => setError(errorText(failure)));
  }, []);

  const show = (FILTERS as readonly string[]).includes(filters.show) ? filters.show as Filter : 'all';
  // One parameter for the column and its direction (-signed), so a click writes the URL once.
  const descending = filters.sort.startsWith('-');
  const sortKey = filters.sort.replace(/^-/, '');
  const sort = (SORTS as readonly string[]).includes(sortKey) ? sortKey as Sort : 'status';
  const needle = filters.search.trim().toLowerCase();
  const narrowing = Boolean(needle) || !['all', 'groups', 'standalone'].includes(show);

  const visible = useMemo(() => {
    if (!rows) return [];
    const byId = new Map(rows.map((row) => [row.id, row]));
    const matches = (row: PortfolioRow) => (!needle || row.name.toLowerCase().includes(needle))
      && (['all', 'groups', 'standalone'].includes(show) || row.status === show);
    const tops = rows.filter((row) => !row.parent || !byId.has(row.parent))
      .filter((row) => show !== 'groups' || row.affiliates.length > 0)
      .filter((row) => show !== 'standalone' || row.affiliates.length === 0);
    const ordering = compare(sort, descending);
    return tops.map((top) => {
      const affiliates = top.affiliates.map((id) => byId.get(id)).filter((row): row is PortfolioRow => Boolean(row));
      const hits = narrowing ? affiliates.filter(matches) : affiliates;
      return { top, affiliates: hits.sort(ordering), total: affiliates.length, shown: matches(top) || hits.length > 0 };
    }).filter((group) => group.shown).sort((a, b) => ordering(a.top, b.top));
  }, [rows, needle, show, sort, descending, narrowing]);

  if (error) return <div className="azure-cost-error">{error}</div>;
  if (!rows) return <p className="text-muted">Loading customers…</p>;
  if (rows.length === 0) {
    return <p className="empty-state">No customers yet. <Link to={settingsLink({ location, label: reportTitle(report) })}>Add a customer</Link> and pick its enrollments.</p>;
  }

  const groups = rows.filter((row) => row.affiliates.length > 0).map((row) => row.id);
  const isOpen = (id: string) => narrowing || expanded.includes(id);
  const toggle = (event: MouseEvent, id: string) => {
    event.stopPropagation();
    setExpanded(expanded.includes(id) ? expanded.filter((open) => open !== id) : [...expanded, id]);
  };
  const counts = Object.fromEntries(STATUS_ORDER.map((status) => [status, rows.filter((row) => row.status === status).length]));

  const header = (key: Sort, label: string) => (
    <th aria-sort={sort === key ? (descending ? 'descending' : 'ascending') : undefined}>
      <button type="button" className="azure-cost-sort" onClick={() => {
        // Money and growth read best largest first; names and statuses from the top.
        const startDescending = key !== 'name' && key !== 'status';
        const nextDescending = sort === key ? !descending : startDescending;
        setFilter('sort', nextDescending ? `-${key}` : key);
      }}>{label}{sort === key ? (descending ? ' ↓' : ' ↑') : ''}</button>
    </th>
  );

  const line = (row: PortfolioRow, affiliate: boolean, total = 0) => (
    <tr key={row.id} className={`azure-cost-clickable ${affiliate ? 'azure-cost-chooser-affiliate' : 'azure-cost-chooser-top'}`}
        onClick={() => navigate(reportLink(report, row.id))}>
      <td>
        {!affiliate && total > 0 ? (
          <button type="button" className="azure-cost-twisty" aria-expanded={isOpen(row.id)} disabled={narrowing}
                  aria-label={`${isOpen(row.id) ? 'Collapse' : 'Expand'} ${row.name}'s affiliates`}
                  onClick={(event) => toggle(event, row.id)}>{isOpen(row.id) ? '▾' : '▸'}</button>
        ) : <span className="azure-cost-twisty-space" />}
        <Link to={reportLink(report, row.id)} onClick={(event) => event.stopPropagation()}>{row.name}</Link>
        <div className="text-muted azure-cost-row-detail">
          {row.enrollments} enrollment{row.enrollments === 1 ? '' : 's'}
          {total > 0 ? ` · ${total} affiliate${total === 1 ? '' : 's'}` : ''}
          {affiliate ? ' · affiliate' : ''}
        </div>
      </td>
      <td>{row.signed != null ? formatMoney(row.signed, row.currency, true) : '—'}</td>
      <td><BurnCell row={row} /></td>
      <td>{row.last_month ? <>{formatMoney(row.last_month.actual, row.currency, true)}
        <div className="text-muted azure-cost-row-detail">{formatMonth(row.last_month.month, true)}</div></> : '—'}</td>
      <td>
        <div className="azure-cost-trend">
          <Sparkline points={row.recent} />
          {row.last_month?.mom_pct != null ? (
            <span className={row.last_month.mom_pct >= 0 ? 'azure-cost-up' : 'azure-cost-down'}>
              {row.last_month.mom_pct >= 0 ? '+' : ''}{row.last_month.mom_pct}%</span>
          ) : null}
        </div>
      </td>
      <td>{projectedText(row)}</td>
      <td>
        <span className={`azure-cost-status ${row.status}`}>
          {row.status === 'parent-macc' && row.covered_by ? `In ${row.covered_by}'s MACC` : STATUS_LABELS[row.status]}</span>
        {row.synced_at ? (
          <div className="text-muted azure-cost-row-detail">
            {row.unsynced_enrollments ? `${row.unsynced_enrollments} of ${row.enrollments} not synced yet · `
              : row.stale ? 'Stale · ' : ''}Synced {syncedText(row.synced_at)}
          </div>
        ) : null}
      </td>
    </tr>
  );

  return (
    <section className="card azure-cost-card">
      <div className="azure-cost-card-head">
        <div className="azure-cost-chips" role="group" aria-label="Show">
          {FILTERS.map((filter) => (
            <button key={filter} type="button" className={show === filter ? 'active' : undefined}
                    aria-pressed={show === filter} onClick={() => setFilter('show', filter)}>
              {FILTER_LABELS[filter]}
              {filter in counts && counts[filter] ? <span className="azure-cost-chip-count">{counts[filter]}</span> : null}
            </button>
          ))}
        </div>
        <div className="azure-cost-toolbar">
          {groups.length ? (
            <>
              <button type="button" className="btn" disabled={narrowing} onClick={() => setExpanded(groups)}>Expand all</button>
              <button type="button" className="btn" disabled={narrowing} onClick={() => setExpanded([])}>Collapse all</button>
            </>
          ) : null}
          <input type="search" placeholder="Search customers and affiliates" value={filters.search}
                 onChange={(event) => setFilter('search', event.target.value)} aria-label="Search customers" />
        </div>
      </div>
      <table className="azure-cost-table azure-cost-chooser">
        <thead>
          <tr>
            {header('name', 'Customer')}
            {header('signed', 'Signed MACC')}
            {header('burn', 'MACC consumed vs term')}
            {header('last', 'Last month')}
            {header('trend', 'Trend')}
            <th>Projected</th>
            {header('status', 'Status')}
          </tr>
        </thead>
        <tbody>
          {visible.flatMap(({ top, affiliates, total }) => [
            line(top, false, total),
            ...(isOpen(top.id) ? affiliates.map((affiliate) => line(affiliate, true)) : []),
          ])}
        </tbody>
      </table>
      {visible.length === 0 ? <p className="text-muted">No customer matches.</p> : null}
    </section>
  );
}
