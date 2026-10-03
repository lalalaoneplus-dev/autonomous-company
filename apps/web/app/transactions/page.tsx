'use client';
import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { Transaction } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';

export default function Transactions() {
  const [items, setItems] = useState<Transaction[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchApi<Transaction[]>('/api/transactions')
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (loading) return <Loading />;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Double-Entry Ledger</h1>
      {!items.length ? <EmptyState message="No transactions." /> : (
        <div className="overflow-x-auto card">
          <table className="w-full text-left text-sm border-collapse">
            <thead className="bg-surface border-b border-border">
              <tr>
                <th className="p-3 font-semibold">Timestamp</th>
                <th className="p-3 font-semibold">Amount (Cents)</th>
                <th className="p-3 font-semibold text-green-600 dark:text-green-400">Debit (Dr)</th>
                <th className="p-3 font-semibold text-red-600 dark:text-red-400">Credit (Cr)</th>
                <th className="p-3 font-semibold">Reference</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono">
              {items.map(item => (
                <tr key={item.id} className="table-row-hover">
                  <td className="p-3 whitespace-nowrap text-gray-500">{new Date(item.created_at).toLocaleString()}</td>
                  <td className="p-3 font-bold">{item.amount_cents.toLocaleString()}</td>
                  <td className="p-3">{item.debit_account || '-'}</td>
                  <td className="p-3">{item.credit_account || '-'}</td>
                  <td className="p-3 truncate max-w-[200px]" title={item.external_reference || item.description}>{item.external_reference || item.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
