import { Fragment, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Breadcrumbs } from '../../pluginHost/breadcrumbs';
import { useUrlState } from '../../pluginHost/state';
import { fetchGuide, type Guide, type GuideService } from './client';
import { DrillLink } from './Drill';
import { errorText, formatMoney, formatMonth } from './format';
import { PopupRow } from './Popup';
import { SolutionDetail } from './Solutions';
import { Loading } from './Loading';
import { useMarketplaceClasses } from './Advisor';

const TABS = { playbooks: 'Playbooks', solutions: 'Solutions', services: 'Services' } as const;
type Tab = keyof typeof TABS;
const ALL = 'All plays';
const money = (value: number) => formatMoney(value, 'USD', true);

function NoteLink({ stem, children }: { stem: string | null | undefined; children: React.ReactNode }) {
  return stem ? <Link to={`/browse/${encodeURIComponent(stem)}`}>{children}</Link> : null;
}

function Chips({ plays, chosen, onChoose }: { plays: string[]; chosen: string; onChoose: (play: string) => void }) {
  return (
    <div className="azure-cost-chips" role="group" aria-label="Solution play">
      {[ALL, ...plays].map((play) => (
        <button key={play} type="button" className={chosen === play ? 'active' : undefined} aria-pressed={chosen === play}
                onClick={() => onChoose(play)}>{play}</button>
      ))}
    </div>
  );
}

function Playbooks({ guide }: { guide: Guide }) {
  const [open, setOpen] = useState<string | null>(null);
  const names = new Map(guide.solutions.map((solution) => [solution.id, solution]));
  if (!guide.playbooks.length) return <p className="empty-state">No Playbook notes in the vault yet (Work/Sales/Playbooks).</p>;
  return (
    <table className="azure-cost-table">
      <thead><tr><th>Playbook</th><th>Solution play</th><th>Solutions it covers</th></tr></thead>
      <tbody>
        {guide.playbooks.map((playbook) => (
          <Fragment key={playbook.stem}>
            <tr className="azure-cost-clickable" onClick={() => setOpen(playbook.stem)}>
              <td><strong>{playbook.name}</strong>{playbook.status === 'draft' ? <span className="text-muted"> · draft</span> : null}</td>
              <td>{playbook.play ?? '—'}</td>
              <td className="text-muted">{playbook.solutions.map((id) => names.get(id)?.name ?? id).join(', ')}</td>
            </tr>
            {open === playbook.stem ? (
              <PopupRow kicker="Playbook" title={playbook.name} onClose={() => setOpen(null)}>
                <p>{playbook.summary}</p>
                <p><NoteLink stem={playbook.stem}>Read the playbook: {playbook.name}</NoteLink></p>
                <h4>Solutions it covers</h4>
                <ul>{playbook.solutions.map((id) => {
                  const solution = names.get(id);
                  return <li key={id}>{solution?.note ? <NoteLink stem={solution.note}>{solution.name}</NoteLink> : (solution?.name ?? id)}
                    {solution?.customers.length ? <span className="text-muted"> · {solution.customers.length} customers run it</span> : null}</li>;
                })}</ul>
              </PopupRow>
            ) : null}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function Solutions({ guide, play, search }: { guide: Guide; play: string; search: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const shown = guide.solutions.filter((solution) => (play === ALL || solution.play === play)
    && solution.name.toLowerCase().includes(search));
  return (
    <table className="azure-cost-table">
      <thead><tr><th>Solution</th><th>Solution play</th><th>Customers running it</th><th>Sized, small – large</th></tr></thead>
      <tbody>
        {shown.map((solution) => (
          <Fragment key={solution.id}>
            <tr className="azure-cost-clickable" onClick={() => setOpen(solution.id)}>
              <td><strong>{solution.name}</strong></td><td>{solution.play}</td><td>{solution.customers.length || '—'}</td>
              <td>{solution.sizing ? `${money(solution.sizing.totals.small)} – ${money(solution.sizing.totals.large)}` : '—'}</td>
            </tr>
            {open === solution.id ? (
              <PopupRow kicker={`Solution · ${solution.play}`} title={solution.name} onClose={() => setOpen(null)}>
                {solution.description ? <p>{solution.description}</p> : null}
                {solution.customers.length ? <p className="text-muted">Run by: {solution.customers.join(', ')}</p> : null}
                <SolutionDetail guide={solution} />
              </PopupRow>
            ) : null}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function ServiceRow({ service, open, onOpen, onClose }: {
  service: GuideService; open: boolean; onOpen: () => void; onClose: () => void;
}) {
  const [classes, classify, classifying, classError] = useMarketplaceClasses(open && Boolean(service.marketplace?.length));
  const keyOf = (product: { publisher: string; offer: string; plan: string }) => `${product.publisher}|${product.offer}|${product.plan}`;
  return (
    <>
      <tr className="azure-cost-clickable" onClick={onOpen}>
        <td><strong>{service.name}</strong>{service.note ? null : <span className="text-muted"> · no note yet</span>}</td>
        <td>{service.play ?? service.category ?? '—'}</td>
        <td>{service.customers.length || '—'}</td>
        <td>{service.monthly ? money(service.monthly) : '—'}</td>
      </tr>
      {open ? (
        <PopupRow kicker="Service" title={service.name} onClose={onClose}>
          <p className="azure-cost-note">
            {service.note ? <NoteLink stem={service.note}>Read about it: {service.note}</NoteLink>
              : <span className="text-muted">No Technology note in the vault for this service yet.</span>}
          </p>
          {service.solutions.length ? (
            <p className="azure-cost-note">Solutions: {service.solutions.map((item, index) => (
              <span key={item.id}>{index ? ', ' : ''}{item.note ? <NoteLink stem={item.note}>{item.name}</NoteLink> : item.name}</span>
            ))}</p>
          ) : null}
          {service.marketplace?.length ? (
            <>
              <h4>What {service.name} is: the Marketplace products behind it</h4>
              <p className="text-muted azure-cost-note">
                Cost Management bills every Marketplace offer as "{service.name}"; the Marketplace charges name each one.
                Monthly averages over the last three closed months, across all customers. "What it is" is Compass's
                reading of the product's names.
              </p>
              {classes && classes.pending ? (
                <div className="azure-cost-toolbar">
                  <button type="button" className="btn" disabled={classifying || !classes.available} onClick={classify}>
                    {classifying ? 'Compass is reading the products…' : `Describe ${classes.pending} products with Compass`}</button>
                </div>
              ) : null}
              {classError ? <div className="azure-cost-error">{classError}</div> : null}
              <table className="azure-cost-table">
                <thead><tr><th>Publisher</th><th>Offer</th><th>What it is</th><th>Kind</th><th>Monthly</th><th>Customers</th></tr></thead>
                <tbody>
                  {service.marketplace.map((product) => (
                    <tr key={`${product.publisher}|${product.offer}|${product.plan}`}>
                      <td>{product.publisher}</td><td>{product.offer}<br /><span className="text-muted">{product.plan}</span></td>
                      <td>{classes?.classified[keyOf(product)] ? (
                        <>
                          <span className="azure-cost-tag-key">{classes.classified[keyOf(product)].category}</span>
                          {classes.classified[keyOf(product)].compass_alternative ? <span className="azure-cost-anomaly new">Compass could serve this</span> : null}
                          <br /><span className="text-muted">{classes.classified[keyOf(product)].what}</span>
                        </>
                      ) : <span className="text-muted">—</span>}</td>
                      <td className="text-muted">{product.recurring ? 'Subscription' : 'Usage-based'}</td>
                      <td>{money(product.monthly)}</td>
                      <td>{product.customers.map((customer, index) => (
                        <span key={customer.id}>{index ? ', ' : ''}
                          <DrillLink kind="service" name={service.name} customerId={customer.id}>{customer.name}</DrillLink></span>
                      ))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
          <h4>Customers using it</h4>
          {service.customers.length ? (
            <table className="azure-cost-table">
              <thead><tr><th>Customer</th><th>Monthly, last 3 closed</th></tr></thead>
              <tbody>
                {service.customers.map((customer) => (
                  <tr key={customer.id}>
                    <td><DrillLink kind="service" name={service.name} customerId={customer.id}>{customer.name}</DrillLink></td>
                    <td>{money(customer.monthly)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-muted">No customer was billed for it in the last three closed months.</p>}
        </PopupRow>
      ) : null}
    </>
  );
}

function Services({ guide, play, search }: { guide: Guide; play: string; search: string }) {
  const [open, setOpen] = useState<string | null>(null);
  const shown = guide.services.filter((service) => (play === ALL || service.play === play)
    && service.name.toLowerCase().includes(search));
  return (
    <table className="azure-cost-table">
      <thead><tr><th>Service</th><th>Solution play</th><th>Customers</th><th>Monthly, all customers</th></tr></thead>
      <tbody>
        {shown.map((service) => (
          <ServiceRow key={service.name} service={service} open={open === service.name}
                      onOpen={() => setOpen(service.name)} onClose={() => setOpen(null)} />
        ))}
      </tbody>
    </table>
  );
}

/** Playbooks, solutions and services in one place, without choosing a customer
 *  (operator, 2026-10-23: "I don't have a way to navigate to it unless I am inside a
 *  customer view"). Every row opens in a popup; a customer there opens its report. */
export function GuidePage() {
  const [guide, setGuide] = useState<Guide | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useUrlState<Tab>('tab', 'playbooks', { valid: Object.keys(TABS) as Tab[] });
  const [play, setPlay] = useState(ALL);
  const [search, setSearch] = useState('');

  useEffect(() => { fetchGuide().then(setGuide, (failure) => setError(errorText(failure))); }, []);

  const plays = useMemo(() => [...new Set((guide?.solutions ?? []).map((solution) => solution.play))], [guide]);
  return (
    <div className="page azure-cost-page">
      <Breadcrumbs items={[{ label: 'Azure Customer 360', to: '/azure-cost-manager' }, { label: 'Solutions Guide' }]} />
      <header className="azure-cost-header"><h1>Solutions Guide</h1></header>
      <p className="text-muted azure-cost-note">
        The sales playbooks, the solutions customers build on Azure and every service they are billed for -- each
        written up in the vault. Customer figures are monthly averages
        {guide?.window?.last_month ? ` to ${formatMonth(guide.window.last_month)}` : ''}; open a customer to see its own.
      </p>
      <div className="azure-cost-toolbar">
        <div className="azure-cost-segmented" role="tablist">
          {(Object.keys(TABS) as Tab[]).map((name) => (
            <button key={name} type="button" role="tab" aria-selected={tab === name} className={tab === name ? 'active' : undefined}
                    onClick={() => setTab(name)}>{TABS[name]}{guide ? ` (${guide[name].length})` : ''}</button>
          ))}
        </div>
        {tab !== 'playbooks' ? (
          <input type="search" placeholder="Search" value={search} onChange={(event) => setSearch(event.target.value)}
                 aria-label="Search" />
        ) : null}
      </div>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {!guide ? <Loading /> : (
        <section className="card azure-cost-card">
          {tab !== 'playbooks' ? <Chips plays={plays} chosen={play} onChoose={setPlay} /> : null}
          {tab === 'playbooks' ? <Playbooks guide={guide} />
            : tab === 'solutions' ? <Solutions guide={guide} play={play} search={search.trim().toLowerCase()} />
              : <Services guide={guide} play={play} search={search.trim().toLowerCase()} />}
        </section>
      )}
    </div>
  );
}
