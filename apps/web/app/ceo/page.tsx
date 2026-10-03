'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { errorMessage } from '@/lib/errors';
import { CEOState } from '@/lib/types';

export default function CEO() {
  const [data, setData] = useState<CEOState | null>(null);
  const [error, setError] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [strategyInput, setStrategyInput] = useState('');

  const load = () => {
    fetchApi<CEOState>('/api/ceo').then(res => {
      setData(res);
      setStrategyInput(res.strategy || '');
    }).catch((cause: unknown) => setError(errorMessage(cause)));
  };
  useEffect(() => { load(); }, []);

  const runCycle = async () => {
    setLoading(true);
    setError('');
    try {
      await fetchApi('/api/ceo/cycle', { method: 'POST', requireOwner: true });
      load();
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  };

  const updateStrategy = async () => {
    setLoading(true);
    setError('');
    try {
      await fetchApi('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify({ strategy: strategyInput }),
        requireOwner: true
      });
      load();
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  };

  if (error && !data) return <ErrorAlert message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight">CEO Operations</h1>
        <button
          onClick={runCycle}
          disabled={loading || data.frozen}
          className="btn-primary"
        >
          {loading ? 'Running...' : 'Execute CEO Cycle'}
        </button>
      </div>

      {error && <ErrorAlert message={error} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="card p-5 space-y-4">
          <h2 className="text-xl font-bold mb-4">Current Instruction</h2>
          <textarea
            className="input-field min-h-[100px]"
            value={strategyInput}
            onChange={e => setStrategyInput(e.target.value)}
            placeholder="High level instruction..."
          />
          <button onClick={updateStrategy} disabled={loading} className="btn-secondary w-full">Update Strategy</button>
        </div>

        <div className="card p-5 space-y-2">
          <h2 className="text-xl font-bold mb-4">State</h2>
          <p><strong>Objective:</strong> {data.objective}</p>
          <p><strong>Owner Goal:</strong> {data.owner_goal}</p>
          <p><strong>Autonomy Level:</strong> {data.autonomy_level}</p>
          <p><strong>Frozen:</strong> {data.frozen ? <span className="text-red-500 font-bold">Yes</span> : 'No'}</p>
        </div>
      </div>
    </div>
  );
}
