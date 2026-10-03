'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { OverviewData } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { PolicyBadge } from '@/components/PolicyBadge';

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    fetchApi<OverviewData>('/api/overview')
      .then(setData)
      .catch(e => setError(e.message));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <h1 className="text-3xl font-bold tracking-tight">Overview</h1>
        <div className="flex gap-2">
          {data.security.frozen && <PolicyBadge status="FROZEN" />}
          <span className="px-3 py-1 bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 rounded font-bold text-sm tracking-widest border border-amber-200 dark:border-amber-800">
            PAPER MODE / REAL MONEY DISABLED
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-1">Paper Treasury (Cents)</h2>
          <p className="text-3xl font-bold font-mono">{data.treasury?.balance_cents?.toLocaleString() || 0}</p>
        </div>
        <div className="card p-5">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-1">Model Cost (Cents)</h2>
          <p className="text-3xl font-bold font-mono text-orange-600 dark:text-orange-400">{data.model_cost_cents?.toLocaleString() || 0}</p>
        </div>
        <div className="card p-5">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-1">Active Experiments</h2>
          <p className="text-3xl font-bold">{data.active_experiments}</p>
        </div>
        <div className="card p-5">
          <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-1">Pending Approvals</h2>
          <p className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">{data.pending_approvals}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-5 space-y-4">
          <h3 className="text-lg font-bold border-b border-border pb-2">System Directives</h3>
          <div><strong className="text-gray-500 text-sm">Objective:</strong> <p>{data.objective}</p></div>
          <div><strong className="text-gray-500 text-sm">Owner Goal:</strong> <p>{data.owner_goal}</p></div>
          <div><strong className="text-gray-500 text-sm">Lifecycle Cycles:</strong> <p>{data.cycle_count}</p></div>
          <div><strong className="text-gray-500 text-sm">Autonomy Level:</strong> <p>{data.autonomy_level}</p></div>
        </div>

        <div className="card p-5 space-y-4">
          <h3 className="text-lg font-bold border-b border-border pb-2">Portfolio Concentration</h3>
          <div className="space-y-3">
            {Object.entries(data.portfolio.streams).map(([name, stream]) => (
              <div key={name} className="rounded border border-border bg-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <strong className="capitalize">{name.replace(/_/g, ' ')}</strong>
                  <span className="font-mono text-xs">risk {stream.committed_risk_cents.toLocaleString()}p</span>
                </div>
                <p className="mt-1 text-xs text-gray-500">
                  {stream.opportunities} opportunities · pipeline downside {stream.pipeline_downside_cents.toLocaleString()}p · {stream.experiments} experiments · paper P/L {(stream.paper_revenue_cents - stream.paper_cost_cents).toLocaleString()}p
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
