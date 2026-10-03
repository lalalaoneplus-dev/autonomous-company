'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { TreasurySnapshot } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';

export default function Treasury() {
  const [data, setData] = useState<TreasurySnapshot | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<TreasurySnapshot>('/api/treasury')
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading || !data) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold tracking-tight">Treasury</h1>
        <span className="rounded border border-amber-300 bg-amber-100 px-3 py-1 text-sm font-bold tracking-wider text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
          PAPER MODE / REAL MONEY DISABLED
        </span>
      </div>

      <div className="card p-6 border-l-4 border-l-amber-500">
        <h2 className="text-sm font-medium text-amber-600 dark:text-amber-400 mb-1 tracking-widest uppercase" data-testid="paper-revenue-label">Paper Balance</h2>
        <p className="text-4xl font-bold font-mono">{data.balance_cents?.toLocaleString()} <span className="text-xl text-gray-400">Cents</span></p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['Paper revenue', data.revenue_cents],
          ['Paper expenses', data.expenses_cents],
          ['Paper profit', data.profit_cents],
          ['Goal reserve', data.goal_reserve_cents ?? 0],
        ].map(([label, value]) => (
          <div key={String(label)} className="card p-4">
            <p className="text-xs uppercase tracking-wider text-gray-500">{label}</p>
            <p className="mt-1 font-mono text-xl font-bold">{Number(value).toLocaleString()}p</p>
          </div>
        ))}
      </div>

      <div className="card p-6 border-l-4 border-l-gray-300 dark:border-l-gray-700 bg-gray-50 dark:bg-gray-900/50">
        <h2 className="text-sm font-medium text-gray-500 mb-1 tracking-widest uppercase">Real Balance (DISABLED)</h2>
        <p className="text-4xl font-bold font-mono text-gray-400">0 <span className="text-xl">Cents</span></p>
      </div>
    </div>
  );
}
