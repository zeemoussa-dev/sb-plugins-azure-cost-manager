/** Something is on its way: a turning circle with what it is waiting for, in the middle
 *  of the space it will fill (operator, 2026-10-23: "a circle rotating while saying
 *  loading, in the center"). */
export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="azure-cost-loading" role="status" aria-live="polite">
      <span className="azure-cost-spinner" aria-hidden="true" />
      <span className="text-muted">{label}</span>
    </div>
  );
}
