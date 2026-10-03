'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { AuditLog } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Audit() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<AuditLog[]>('/api/audit')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Immutable Audit Log</h1>
      {!items.length ? <EmptyState message="No events in audit log." /> : (
        <div className="overflow-x-auto card">
          <table className="w-full text-left text-sm border-collapse">
            <thead className="bg-surface border-b border-border">
              <tr>
                <th className="p-3 font-semibold">Timestamp</th>
                <th className="p-3 font-semibold">Actor</th>
                <th className="p-3 font-semibold">Event</th>
                <th className="p-3 font-semibold">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map(item => (
                <tr key={item.id} className="table-row-hover">
                  <td className="p-3 whitespace-nowrap text-gray-500 font-mono">{new Date(item.created_at).toLocaleString()}</td>
                  <td className="p-3 font-semibold uppercase">{item.actor}</td>
                  <td className="p-3 font-mono">{item.event_type}</td>
                  <td className="p-3 max-w-sm"><span className="block">{item.rationale}</span><span className="block truncate text-xs text-gray-500" title={JSON.stringify(item.payload)}>{JSON.stringify(item.payload)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
