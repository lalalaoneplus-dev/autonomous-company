'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Project } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Projects() {
  const [items, setItems] = useState<Project[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<Project[]>('/api/projects')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Projects (OWNER_DELIVERY_DECISION Gate)</h1>
      <p className="text-gray-500">Commercial projects awaiting final owner choice between real execution or paper simulation.</p>

      {!items.length ? <EmptyState message="No active projects." /> : (
        <div className="grid gap-4">
          {items.map(item => (
            <div key={item.id} className="card p-5">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h3 className="font-bold">{item.name}</h3>
                <span className="rounded bg-gray-200 px-2 py-1 text-xs font-bold uppercase dark:bg-gray-800">{item.status}</span>
              </div>
              <p className="mt-2 text-sm">{item.concept}</p>
              <p className="mt-2 text-xs text-gray-500">Audience: {item.audience || 'not set'} · paper price: {item.price_cents}p · {new Date(item.created_at).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
