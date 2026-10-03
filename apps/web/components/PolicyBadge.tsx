export function PolicyBadge({ status }: { status: string }) {
  let color = 'bg-gray-600 text-white';
  if (status === 'ALLOW' || status === 'APPROVED') color = 'bg-green-600 text-white';
  if (status === 'DENY' || status === 'DENIED') color = 'bg-red-600 text-white';
  if (status === 'REQUIRE_APPROVAL' || status === 'PENDING') color = 'bg-yellow-500 text-black';
  if (status === 'EDIT_AND_APPROVE') color = 'bg-blue-600 text-white';
  if (status === 'operator_attested_source_receipt') color = 'bg-blue-700 text-white';
  const label = status === 'operator_attested_source_receipt' ? 'operator attested' : status.replace(/_/g, ' ');

  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wide ${color}`}>
      {label}
    </span>
  );
}
