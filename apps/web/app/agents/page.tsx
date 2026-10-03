'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Agent } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<Agent[]>('/api/agents')
      .then(setAgents)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Specialist Agents</h1>
      {!agents.length ? <EmptyState message="No agents defined." /> : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map(a => (
            <div key={a.id} className="card p-5">
              <h3 className="font-bold text-lg capitalize">{a.role.replace(/_/g, ' ')}</h3>
              <p className="text-sm text-gray-500 mt-2">{a.instructions}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {a.permissions.map(permission => <span key={permission} className="rounded bg-gray-100 px-2 py-1 text-[11px] dark:bg-gray-800">{permission}</span>)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
