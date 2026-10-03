'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Approval } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';
import { PolicyBadge } from '@/components/PolicyBadge';
import { errorMessage } from '@/lib/errors';

export default function Approvals() {
  const [items, setItems] = useState<Approval[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [editStates, setEditStates] = useState<Record<string, string>>({});

  const load = () => {
    fetchApi<Approval[]>('/api/approvals')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleDecision = async (id: string, decision: 'APPROVE' | 'DENY' | 'EDIT_AND_APPROVE') => {
    setActionLoading(id);
    setError('');
    try {
      const body: { decision: typeof decision; actor: string; edits?: Record<string, unknown> } = { decision, actor: 'owner' };
      if (decision === 'EDIT_AND_APPROVE') {
        const editsStr = editStates[id];
        if (!editsStr) throw new Error("Must provide edits JSON");
        try {
          body.edits = JSON.parse(editsStr);
        } catch {
          throw new Error("Invalid JSON in edits");
        }
      }

      await fetchApi(`/api/approvals/${id}/decision`, {
        method: 'POST',
        body: JSON.stringify(body),
        requireOwner: true
      });
      load();
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && !items.length) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Approvals</h1>
      {error && <ErrorAlert message={error} />}

      {!items.length ? <EmptyState message="No pending approvals." /> : (
        <div className="grid gap-6">
          {items.map(item => (
            <div key={item.id} className="card p-5 space-y-4">
              <div className="flex justify-between items-start border-b border-border pb-4">
                <div>
                  <h3 className="font-bold text-lg font-mono">{item.action_type}</h3>
                  <p className="text-sm text-gray-500 mt-1">{item.approval_class} · requested by {item.requested_by}</p>
                </div>
                <PolicyBadge status={item.status} />
              </div>

              <div className="bg-surface p-4 rounded text-sm font-mono overflow-auto max-h-[300px] border border-border">
                <p className="mb-2 font-sans">{item.reason}</p>
                <pre className="whitespace-pre-wrap">{JSON.stringify(item.payload, null, 2)}</pre>
              </div>

              {item.status === 'PENDING' && (
                <div className="flex flex-col gap-4 pt-2">
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDecision(item.id, 'APPROVE')}
                      disabled={actionLoading === item.id}
                      className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded font-medium disabled:opacity-50 transition-colors"
                    >
                      {actionLoading === item.id ? 'Processing...' : 'APPROVE'}
                    </button>
                    <button
                      onClick={() => handleDecision(item.id, 'DENY')}
                      disabled={actionLoading === item.id}
                      className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded font-medium disabled:opacity-50 transition-colors"
                    >
                      {actionLoading === item.id ? 'Processing...' : 'DENY'}
                    </button>
                  </div>

                  <div className="border-t border-border pt-4 mt-2">
                    <p className="text-sm font-semibold mb-2">Edit & Approve</p>
                    <textarea
                      className="input-field mb-2 font-mono text-sm"
                      rows={3}
                      placeholder='{"key": "value"}'
                      value={editStates[item.id] || ''}
                      onChange={e => setEditStates({...editStates, [item.id]: e.target.value})}
                    />
                    <button
                      onClick={() => handleDecision(item.id, 'EDIT_AND_APPROVE')}
                      disabled={actionLoading === item.id || !editStates[item.id]}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded font-medium disabled:opacity-50 transition-colors"
                    >
                      EDIT_AND_APPROVE
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
