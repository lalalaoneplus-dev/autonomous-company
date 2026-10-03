'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Experiment } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';
import { PolicyBadge } from '@/components/PolicyBadge';

export default function Experiments() {
  const [items, setItems] = useState<Experiment[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<Experiment[]>('/api/experiments')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Experiments</h1>
      {!items.length ? <EmptyState message="No simulated experiments found." /> : (
        <div className="grid gap-4">
          {items.map(item => (
            <div key={item.id} className="card p-5 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
              <div>
                <h3 className="font-bold text-lg">{item.title}</h3>
                <p className="mt-1 text-sm">{item.hypothesis}</p>
                <div className="text-sm text-gray-500 mt-1 font-mono">
                  {item.stream_type.replace(/_/g, ' ')} · Budget: {item.max_spend_cents}p · Cost: {item.expenses_cents}p · Revenue: {item.revenue_cents}p · P/L: {item.profit_cents}p
                </div>
              </div>
              <div className="flex flex-col items-end gap-2">
                <PolicyBadge status={item.status} />
                {item.outcome_action && <span className="text-sm font-semibold px-2 py-1 bg-gray-100 dark:bg-gray-800 rounded">{item.outcome_action}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
