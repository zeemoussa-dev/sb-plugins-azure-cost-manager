import { useEffect, useState } from 'react';
import {
  fetchTaggingGuide, fetchTaggingPlan, writeTaggingGuide, writeTaggingPlan,
  type Kept, type TagGaps, type TaggingMove, type TaggingPlan,
} from './client';
import { KeptTextButton, useRememberedFold } from './CompassText';
import { errorText, formatMoney, formatMonth } from './format';
import { Loading } from './Loading';

const MOVE_LABELS: Record<TaggingMove['kind'], string> = {
  adopt_key: 'Adopt the tag',
  standardize_key: 'One spelling of the key',
  normalize_values: 'One spelling per value',
  inherit: 'Inherit',
  enforce_policy: 'Enforce with Azure Policy',
  backfill: 'Backfill',
  allocate_untagged: 'Allocate untagged cost',
};

/** Compass's tagging plan over the gaps (operator, 2026-10-24): which keys and values to
 *  standardize, what inheritance and policy fill, and what the seller can offer. The
 *  coverage shown is the plugin's figure, never the model's. */
export function TaggingPlanCard({ customerId, currency, accounts }: {
  customerId: string; currency: string | null; accounts?: string[];
}) {
  const [found, setFound] = useState<Kept<TaggingPlan> | null>(null);
  const [writing, setWriting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, fold] = useRememberedFold('azure-cost-manager.tagging-plan-folded');
  useEffect(() => {
    setFound(null);
    fetchTaggingPlan(customerId, accounts).then(setFound, (failure) => setError(errorText(failure)));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId, accounts?.join(',')]);
  const write = () => {
    setWriting(true); setError(null);
    writeTaggingPlan(customerId, accounts).then(setFound, (failure) => setError(errorText(failure))).finally(() => setWriting(false));
  };
  if (!found) return error ? <div className="azure-cost-error">{error}</div> : null;
  const plan = found.value;
  return (
    <details className="card azure-cost-card azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head">
        <h3>Tagging plan</h3>
        {plan && !open ? <span className="text-muted">{plan.moves.length} move{plan.moves.length === 1 ? '' : 's'}{found.stale ? ' · out of date' : ''}</span> : null}
        {/* preventDefault: a click on the button must not fold the card. */}
        <button type="button" className="btn btn-primary" disabled={writing || !found.available}
                onClick={(event) => { event.preventDefault(); fold(true); write(); }}
                title={found.available ? 'Compass weighs the coverage, spellings, drifting values, subscription names, what the customer runs and what you told it'
                  : 'Compass is not available to plugins on this install'}>
          {plan ? 'Ask again' : 'Ask Compass for a tagging plan'}</button>
      </summary>
      {error ? <div className="azure-cost-error">{error}</div> : null}
      {writing ? <Loading label="Compass is weighing which tags to fix first…" /> : plan ? (
        <>
          {found.stale ? <p className="azure-cost-warning">The tags have changed since. Ask again for the latest.</p> : null}
          <p>{plan.summary}</p>
          {plan.moves.length ? (
            <table className="azure-cost-table">
              <thead><tr><th>Move</th><th>Tag</th><th>Tagged now</th><th>Untagged / month</th><th>Effort</th><th>What and why</th></tr></thead>
              <tbody>
                {plan.moves.map((move) => (
                  <tr key={`${move.kind}|${move.dimension}|${move.detail}`}>
                    <td>{MOVE_LABELS[move.kind]}</td>
                    <td>{move.dimension}</td>
                    <td>{move.coverage_pct != null ? `${move.coverage_pct}%` : 'not used'}</td>
                    <td>{move.untagged_last_month != null ? formatMoney(move.untagged_last_month, currency) : '—'}</td>
                    <td>{move.effort}</td>
                    <td>{move.detail}{move.why ? <><br /><span className="text-muted">{move.why}</span></> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {plan.offer ? <><h4>What you can offer</h4><p>{plan.offer}</p></> : null}
          {plan.questions.length ? (
            <><h4>Ask the customer</h4><ul>{plan.questions.map((question) => <li key={question}>{question}</li>)}</ul></>
          ) : null}
          <p className="text-muted azure-cost-note">Compass's plan. Coverage and untagged spend are the plugin's, from the last closed month.</p>
        </>
      ) : <p className="text-muted">Compass turns the gaps below into which tags to fix first, how, and what to offer.</p>}
    </details>
  );
}

/** Tagging guidance to hand the customer (operator, 2026-10-24). */
export function TaggingGuideButton({ customerId, customerName, accounts }: {
  customerId: string; customerName: string; accounts?: string[];
}) {
  return (
    <KeptTextButton label="Tagging guidance" kicker="Tagging guidance for the customer" title={customerName}
                    hint="Tagging guidance for the customer's cloud and finance teams, written by Compass"
                    read={() => fetchTaggingGuide(customerId, accounts)} write={() => writeTaggingGuide(customerId, accounts)}
                    source="Written by Compass from this customer's own tags only — nothing about pitches, quota or pipeline. Check before you send it."
                    writingLabel="Compass is writing the tagging guidance — this can take a minute…" />
  );
}

/** The gaps against the six business dimensions, as computed: what is not used, what
 *  covers too little, the key spellings and the values that drift. */
export function TaggingGaps({ gaps, currency }: { gaps: TagGaps; currency: string | null }) {
  const named = gaps.environment_in_subscription_names;
  const [open, fold] = useRememberedFold('azure-cost-manager.tagging-gaps-folded');
  const short = gaps.dimensions.filter((item) => !item.used || item.below_target).length;
  return (
    <details className="card azure-cost-card azure-cost-fold" open={open}
             onToggle={(event) => { const nowOpen = (event.target as HTMLDetailsElement).open; if (nowOpen !== open) fold(nowOpen); }}>
      <summary className="azure-cost-fold-head">
        <h3>Tagging gaps</h3>
        {!open ? <span className="text-muted">{short} of {gaps.dimensions.length} tags short of the target</span> : null}
      </summary>
      <p className="text-muted azure-cost-note">
        Against six business tags — Environment, Project, Application, Business unit, Owner, Cost centre — with
        {` ${gaps.coverage_target_pct}%`} of the spend tagged as the target. {gaps.tag_keys} tag keys are in use on these enrollments.
      </p>
      <table className="azure-cost-table">
        <thead><tr><th>Tag</th><th>Tagged, last month</th><th>Trend</th><th>Untagged / month</th><th>Key spellings</th><th>Values written several ways</th></tr></thead>
        <tbody>
          {gaps.dimensions.map((item) => (
            <tr key={item.dimension}>
              <td>{item.dimension}</td>
              {item.used ? (
                <>
                  <td className={item.below_target ? 'azure-cost-warning' : undefined}>
                    {item.coverage_pct != null ? `${item.coverage_pct}%` : '—'}</td>
                  <td className="text-muted">{(item.coverage_trend ?? []).length > 1
                    ? `${item.coverage_trend![0].coverage_pct}% in ${formatMonth(item.coverage_trend![0].month, true)} → ${item.coverage_trend![item.coverage_trend!.length - 1].coverage_pct}%`
                    : '—'}</td>
                  <td>{formatMoney(item.untagged_last_month ?? 0, currency)}</td>
                  <td>{(item.spellings ?? []).length > 1
                    ? (item.spellings ?? []).map((key) => <code key={key} className="azure-cost-tag-key">{key}</code>)
                    : (item.spellings ?? [])[0] ?? '—'}</td>
                  <td className="text-muted">{(item.value_drift ?? []).length
                    ? (item.value_drift ?? []).map((drift) => `${drift.value}: ${drift.written_as.join(', ')}`).join(' · ')
                    : '—'}</td>
                </>
              ) : <td colSpan={5} className="azure-cost-warning">Not used on these enrollments</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {named.subscriptions ? (
        <p className="azure-cost-note">
          {named.subscriptions} of {named.of_subscriptions} subscriptions say their environment in their name
          ({named.share_pct != null ? `${named.share_pct}% of the spend` : 'part of the spend'}): an Environment tag on each,
          inherited by what runs in it, would tag that spend without touching a resource.
        </p>
      ) : null}
      {gaps.enrollments_without_tags.length ? (
        <p className="text-muted azure-cost-note">
          No tag keys were found on {gaps.enrollments_without_tags.join(', ')}: untagged, or tags not readable there.
          Their spend is left out of the coverage above.
        </p>
      ) : null}
      <p className="text-muted azure-cost-note">
        Coverage is of the spend tags can be on: commitment purchases and third-party software billed as VM licenses
        carry no resource tags and are left out.
      </p>
    </details>
  );
}
