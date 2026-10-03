'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { SecurityState, SettingsData } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { PolicyBadge } from '@/components/PolicyBadge';

export default function Security() {
  const [data, setData] = useState<SecurityState | null>(null);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchApi<SecurityState>('/api/security'), fetchApi<SettingsData>('/api/settings')])
      .then(([security, currentSettings]) => {
        setData(security);
        setSettings(currentSettings);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading || !data || !settings) return <Loading />;

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Security & Governance</h1>

      <div className="card p-6 space-y-6">
        <div>
          <h2 className="text-sm text-gray-500 uppercase tracking-widest font-bold mb-2">Kill Switch Status</h2>
          <div className="flex items-center gap-4">
            <PolicyBadge status={data.frozen ? 'FROZEN' : 'ACTIVE'} />
            <span className="text-gray-600 dark:text-gray-400">
              {data.frozen ? 'System is completely halted. No automated operations will run.' : 'Operations are running normally under deterministic policy constraints.'}
            </span>
          </div>
        </div>

        <div className="border-t border-border pt-6">
          <h2 className="text-sm text-gray-500 uppercase tracking-widest font-bold mb-4">Hardcoded Invariants</h2>
          <ul className="space-y-3 font-mono">
            <li className="flex justify-between items-center p-3 bg-surface rounded border border-border">
              <span>Autonomy Level</span>
              <span className="font-bold text-blue-600 dark:text-blue-400">{settings.autonomy_level}</span>
            </li>
            <li className="flex justify-between items-center p-3 bg-surface rounded border border-border">
              <span>Real Money</span>
              <span className="font-bold text-red-600 dark:text-red-400">{settings.real_money_enabled ? 'ENABLED' : 'DISABLED'}</span>
            </li>
            <li className="flex justify-between items-center p-3 bg-surface rounded border border-border">
              <span>Default Policy</span>
              <span className="font-bold">REQUIRE_APPROVAL</span>
            </li>
          </ul>
        </div>

        <div className="border-t border-border pt-6">
          <h2 className="mb-3 text-sm font-bold uppercase tracking-widest text-gray-500">Recent security events</h2>
          {data.events.length ? (
            <ul className="space-y-2 text-sm">
              {data.events.map((event) => (
                <li key={event.id} className="rounded border border-border bg-surface p-3">
                  <span className="font-bold">{event.severity}</span> · {event.event_type}
                  <span className="block text-xs text-gray-500">{new Date(event.created_at).toLocaleString()}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-gray-500">No security events recorded.</p>}
        </div>
      </div>
    </div>
  );
}
