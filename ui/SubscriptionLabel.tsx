// Cost Management names a subscription "SUB-ENAI-DEV01(57e76ab1-a2fb-482a-a0ff-cf89d86151fc)":
// the name a person reads, then the id. Shown on one line the id drowned the name
// (operator, 2026-10-23), so the id goes underneath, smaller.
const WITH_ID = /^(.*?)\s*\(([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\)\s*$/i;

export function splitSubscription(full: string): { name: string; id: string | null } {
  const match = WITH_ID.exec(full);
  return match && match[1] ? { name: match[1], id: match[2] } : { name: full, id: null };
}

export function SubscriptionLabel({ name }: { name: string }) {
  const { name: shown, id } = splitSubscription(name);
  if (!id) return <>{shown}</>;
  return (
    <span className="azure-cost-subscription" title={name}>
      <span>{shown}</span>
      <span className="azure-cost-subscription-id">{id}</span>
    </span>
  );
}
