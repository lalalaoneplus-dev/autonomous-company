'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { MemoryEntry } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Memory() {
  const [items, setItems] = useState<MemoryEntry[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<MemoryEntry[]>('/api/memory')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Agent Memory Context</h1>
      {!items.length ? <EmptyState message="No memory entries found." /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {items.map(item => (
            <div key={item.id} className="card p-5">
              <div className="flex gap-2 mb-2">
                <span className="px-2 py-1 bg-gray-200 dark:bg-gray-800 rounded text-xs font-bold uppercase">{item.kind}</span>
                {item.tags.map(tag => <span key={tag} className="px-2 py-1 bg-gray-100 dark:bg-gray-900 rounded text-xs text-gray-500 border border-border">{tag}</span>)}
              </div>
              <pre className="text-sm font-mono whitespace-pre-wrap mt-4 text-gray-700 dark:text-gray-300">{JSON.stringify(item.content, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
