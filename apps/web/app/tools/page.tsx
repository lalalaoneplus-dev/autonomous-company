'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { ToolConfig } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Tools() {
  const [items, setItems] = useState<ToolConfig[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<ToolConfig[]>('/api/tools')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Tool Registry</h1>
      {!items.length ? <EmptyState message="No tools registered in broker." /> : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.map(item => (
            <div key={item.name} className="card p-5">
              <h3 className="font-bold text-lg font-mono text-blue-600 dark:text-blue-400">{item.name}</h3>
              <p className="text-sm mt-2 text-gray-600 dark:text-gray-400">{item.description}</p>
              <p className="mt-3 text-xs uppercase text-gray-500">{item.category} · {item.risk_class} risk · autonomy {item.required_autonomy_level}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
