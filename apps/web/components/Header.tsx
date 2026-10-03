'use client';
import { useState, useEffect } from 'react';
import { fetchApi } from '@/lib/api';
import { SecurityState } from '@/lib/types';
import { errorMessage } from '@/lib/errors';

export function Header() {
  const [frozen, setFrozen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    fetchApi<SecurityState>('/api/security').then(data => setFrozen(data.frozen)).catch(error => setError(errorMessage(error)));
  };

  useEffect(() => { load(); }, []);

  const toggleFreeze = async () => {
    setLoading(true);
    setError('');
    try {
      if (frozen) {
        await fetchApi('/api/security/unfreeze', { method: 'POST', requireOwner: true });
      } else {
        await fetchApi('/api/security/freeze', {
          method: 'POST',
          body: JSON.stringify({ reason: 'Manual toggle from header UI' }),
          requireOwner: true
        });
      }
      load();
    } catch (error: unknown) {
      setError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <header className="h-16 bg-surface border-b border-border flex items-center justify-between gap-2 px-3 pl-16 sticky top-0 z-10 sm:px-4 sm:pl-16 md:px-6">
      <div className="font-semibold text-lg flex min-w-0 items-center gap-4">
        Dashboard
        <span className="hidden lg:inline-flex text-xs px-2 py-1 bg-gray-200 dark:bg-gray-800 rounded font-bold uppercase tracking-wider text-gray-600 dark:text-gray-300">
          PAPER MODE : REAL MONEY DISABLED
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2 sm:gap-4">
        {error && <div className="hidden text-xs text-red-500 max-w-[200px] truncate sm:block">{error}</div>}
        <button
          onClick={toggleFreeze}
          disabled={loading}
          className={`whitespace-nowrap px-3 py-2 text-xs rounded font-bold text-white transition-all shadow-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-surface sm:px-4 sm:text-sm ${frozen ? 'bg-orange-600 hover:bg-orange-700 ring-orange-500' : 'bg-red-600 hover:bg-red-700 ring-red-500'}`}
        >
          <span className="sm:hidden">{loading ? 'WAIT' : frozen ? 'UNFREEZE' : 'FREEZE'}</span>
          <span className="hidden sm:inline">{loading ? 'Processing...' : frozen ? 'UNFREEZE AUTONOMY' : 'FREEZE AUTONOMY'}</span>
        </button>
      </div>
    </header>
  );
}
