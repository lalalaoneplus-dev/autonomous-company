'use client';

import { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { errorMessage } from '@/lib/errors';
import { DemandEvidence, Negotiation, Opportunity, PortfolioSnapshot, ProgramScope } from '@/lib/types';
import { Loading } from '@/components/ui/Loading';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { EmptyState } from '@/components/ui/EmptyState';
import { PolicyBadge } from '@/components/PolicyBadge';

interface FunnelData {
  opportunities: Opportunity[];
  evidence: DemandEvidence[];
  negotiations: Negotiation[];
  portfolio: PortfolioSnapshot;
  bountyPrograms: ProgramScope[];
}

export default function Opportunities() {
  const [data, setData] = useState<FunnelData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      fetchApi<Opportunity[]>('/api/opportunities'),
      fetchApi<DemandEvidence[]>('/api/demand-evidence'),
      fetchApi<Negotiation[]>('/api/negotiations'),
      fetchApi<PortfolioSnapshot>('/api/portfolio'),
      fetchApi<ProgramScope[]>('/api/bug-bounty/programs'),
    ])
      .then(([opportunities, evidence, negotiations, portfolio, bountyPrograms]) =>
        setData({ opportunities, evidence, negotiations, portfolio, bountyPrograms }))
      .catch((cause: unknown) => setError(errorMessage(cause)));
  }, []);

  if (error) return <ErrorAlert message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Revenue Portfolio</h1>
        <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">Evidence before build. Agreement before work. Owner decision before delivery.</p>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Demand evidence</h2>
        {!data.evidence.length ? <EmptyState message="No demand evidence captured." /> : (
          <div className="grid gap-4 lg:grid-cols-2">
            {data.evidence.map((item) => {
              const demo = item.source_url.includes('example.com');
              return (
                <article key={item.id} className="card p-5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <a href={item.source_url} target="_blank" rel="noreferrer" className="font-semibold text-blue-600 hover:underline dark:text-blue-400">{item.source_platform}</a>
                      {demo && <span className="ml-2 rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-purple-800" data-testid="demo-label">Demo</span>}
                      <p className="text-sm text-gray-600 dark:text-gray-400">Buyer: {item.buyer_identity}</p>
                    </div>
                    <PolicyBadge status={item.verification_status} />
                  </div>
                  <blockquote className="my-3 border-l-2 border-blue-500 pl-3 text-sm">{item.quoted_need}</blockquote>
                  <div className="grid gap-1 text-xs text-gray-600 dark:text-gray-400 sm:grid-cols-2">
                    <span>Budget: {item.stated_budget_cents == null ? 'not stated' : new Intl.NumberFormat(undefined, { style: 'currency', currency: item.stated_currency ?? 'USD' }).format(item.stated_budget_cents / 100)}</span>
                    <span>Captured: {new Date(item.captured_at).toLocaleString()}</span>
                    <span>Checked: {new Date(item.status_checked_at).toLocaleString()}</span>
                    <span>External content: {item.external_content_untrusted ? 'untrusted data' : 'not marked'}</span>
                    {item.verification_status === 'operator_attested_source_receipt' && <span>Source proof: operator capture, not platform-signed</span>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Opportunities by stream</h2>
        {!data.opportunities.length ? <EmptyState message="No opportunities evaluated." /> : (
          <div className="overflow-x-auto card">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface">
                <tr><th className="p-3">Stream</th><th className="p-3">Opportunity</th><th className="p-3">State</th><th className="p-3">Score</th><th className="p-3">Paper upside / downside</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.opportunities.map((item) => (
                  <tr key={item.id} className="table-row-hover">
                    <td className="p-3 capitalize">{item.stream_type.replace(/_/g, ' ')}</td>
                    <td className="p-3 font-medium">{item.title}</td>
                    <td className="p-3"><PolicyBadge status={item.status} /></td>
                    <td className="p-3 font-mono">{item.score_bps}</td>
                    <td className="p-3 font-mono">{item.expected_revenue_cents}p / {item.max_downside_cents}p</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-3">
          <h2 className="text-xl font-semibold">Buyer negotiations</h2>
          {!data.negotiations.length ? <EmptyState message="No buyer negotiation imported." /> : data.negotiations.map((item) => (
            <article key={item.id} className="card p-4">
              <div className="flex items-center justify-between gap-2"><strong>{item.counterparty_identity}</strong><PolicyBadge status={item.state} /></div>
              <p className="mt-2 text-sm">{item.requested_product}</p>
              <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">Agreement: {item.counterparty_agreed ? 'configured-adapter receipt accepted (not platform-signed)' : 'not confirmed'} · owner go: {item.owner_go ? 'yes' : 'no'} · delivery: {item.owner_delivery_decision ?? 'not decided'}</p>
            </article>
          ))}
        </div>

        <div className="space-y-3">
          <h2 className="text-xl font-semibold">Bug-bounty programs</h2>
          {!data.bountyPrograms.length ? <EmptyState message="No program scope imported. Active testing is disabled." /> : data.bountyPrograms.map((program) => (
            <article key={program.id} className="card p-4">
              <div className="flex items-center justify-between gap-2"><a href={program.program_url} target="_blank" rel="noreferrer" className="font-semibold text-blue-600 hover:underline dark:text-blue-400">Program scope</a><PolicyBadge status={program.status} /></div>
              <p className="mt-2 text-sm">In scope: {program.assets_in_scope.join(', ')}</p>
              <p className="mt-2 text-xs text-gray-600 dark:text-gray-400">Safe harbor: {program.safe_harbor || 'not recorded — hard stop'} · target authorized: {program.owner_target_authorized ? 'yes' : 'no'}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-xl font-semibold">Portfolio caps</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {Object.entries(data.portfolio.caps_bps).map(([name, bps]) => (
            <div key={name} className="rounded border border-border bg-surface p-3">
              <p className="text-xs capitalize text-gray-600 dark:text-gray-400">{name.replace(/_/g, ' ')}</p>
              <strong className="font-mono">{(bps / 100).toFixed(0)}%</strong>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
