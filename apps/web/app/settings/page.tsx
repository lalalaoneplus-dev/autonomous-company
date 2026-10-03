'use client';

import { useEffect, useState, type FormEvent } from 'react';
import { ErrorAlert } from '@/components/ui/ErrorAlert';
import { fetchApi } from '@/lib/api';
import { errorMessage } from '@/lib/errors';
import { SettingsData } from '@/lib/types';

type SettingsForm = {
  autonomy_level: string;
  global_spend_limit_cents: string;
  per_transaction_limit_cents: string;
  daily_spend_limit_cents: string;
  approval_threshold_cents: string;
  model_cost_limit_cents: string;
  api_cost_limit_cents: string;
  category_allowlist: string;
  category_denylist: string;
  category_limits_cents: string;
  counterparty_allowlist: string;
  counterparty_denylist: string;
  domain_allowlist: string;
  domain_denylist: string;
  rate_limits: string;
};

const numericFields = [
  'autonomy_level',
  'global_spend_limit_cents',
  'per_transaction_limit_cents',
  'daily_spend_limit_cents',
  'approval_threshold_cents',
  'model_cost_limit_cents',
  'api_cost_limit_cents',
] as const;

const jsonFields = [
  'category_allowlist',
  'category_denylist',
  'category_limits_cents',
  'counterparty_allowlist',
  'counterparty_denylist',
  'domain_allowlist',
  'domain_denylist',
  'rate_limits',
] as const;

const numericMeta = [
  { key: 'autonomy_level', label: 'Autonomy level', min: 0, max: 6 },
  { key: 'global_spend_limit_cents', label: 'Global spend limit (cents)', min: 0 },
  { key: 'per_transaction_limit_cents', label: 'Per-transaction limit (cents)', min: 0 },
  { key: 'daily_spend_limit_cents', label: 'Daily spend limit (cents)', min: 0 },
  { key: 'approval_threshold_cents', label: 'Approval threshold (cents)', min: 0 },
  { key: 'model_cost_limit_cents', label: 'Model cost limit (cents)', min: 0 },
  { key: 'api_cost_limit_cents', label: 'API cost limit (cents)', min: 0 },
] as const;

const jsonMeta = [
  { key: 'category_allowlist', label: 'Category allowlist', example: '[]' },
  { key: 'category_denylist', label: 'Category denylist', example: '[]' },
  { key: 'category_limits_cents', label: 'Category limits (cents)', example: '{}' },
  { key: 'counterparty_allowlist', label: 'Counterparty allowlist', example: '[]' },
  { key: 'counterparty_denylist', label: 'Counterparty denylist', example: '[]' },
  { key: 'domain_allowlist', label: 'Domain allowlist', example: '[]' },
  { key: 'domain_denylist', label: 'Domain denylist', example: '[]' },
  { key: 'rate_limits', label: 'Rate limits', example: '{"*":{"max_requests":60,"window_seconds":60}}' },
] as const;

function prettyJson(value: unknown, fallback: string): string {
  return JSON.stringify(value ?? JSON.parse(fallback), null, 2);
}

function formFromSettings(settings: SettingsData): SettingsForm {
  const controls = settings.policy_controls;
  return {
    autonomy_level: String(settings.autonomy_level),
    global_spend_limit_cents: String(settings.limits.global_spend_cents),
    per_transaction_limit_cents: String(settings.limits.per_transaction_cents),
    daily_spend_limit_cents: String(settings.limits.daily_spend_cents),
    approval_threshold_cents: String(settings.limits.approval_threshold_cents),
    model_cost_limit_cents: String(settings.limits.model_cost_limit_cents),
    api_cost_limit_cents: String(settings.limits.api_cost_limit_cents),
    category_allowlist: prettyJson(controls.category_allowlist, '[]'),
    category_denylist: prettyJson(controls.category_denylist, '[]'),
    category_limits_cents: prettyJson(controls.category_limits_cents, '{}'),
    counterparty_allowlist: prettyJson(controls.counterparty_allowlist, '[]'),
    counterparty_denylist: prettyJson(controls.counterparty_denylist, '[]'),
    domain_allowlist: prettyJson(controls.domain_allowlist, '[]'),
    domain_denylist: prettyJson(controls.domain_denylist, '[]'),
    rate_limits: prettyJson(controls.rate_limits, '{"*":{"max_requests":60,"window_seconds":60}}'),
  };
}

export default function Settings() {
  const [token, setToken] = useState('');
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [form, setForm] = useState<SettingsForm | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const existing = sessionStorage.getItem('ownerToken');
    if (existing) setSaved(true);
    fetchApi<SettingsData>('/api/settings')
      .then((data) => {
        setSettings(data);
        setForm(formFromSettings(data));
      })
      .catch((cause: unknown) => setError(errorMessage(cause)));
  }, []);

  const updateField = (field: keyof SettingsForm, value: string) => {
    setForm((current) => (current ? { ...current, [field]: value } : current));
    setError('');
    setNotice('');
  };

  const handleSettingsSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form) return;
    setError('');
    setNotice('');

    const payload: Record<string, unknown> = {};
    for (const field of numericFields) {
      const value = Number(form[field]);
      if (!Number.isInteger(value) || value < 0 || (field === 'autonomy_level' && value > 6)) {
        setError(`${field.replaceAll('_', ' ')} must be a non-negative integer.`);
        return;
      }
      payload[field] = value;
    }
    for (const field of jsonFields) {
      try {
        payload[field] = JSON.parse(form[field]);
      } catch {
        setError(`${field.replaceAll('_', ' ')} must contain valid JSON.`);
        return;
      }
    }

    setSaving(true);
    try {
      const updated = await fetchApi<SettingsData>('/api/settings', {
        method: 'PATCH',
        body: JSON.stringify(payload),
        requireOwner: true,
      });
      setSettings(updated);
      setForm(formFromSettings(updated));
      setNotice('Owner settings saved. Real-money execution remains forced off.');
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  };

  const handleTokenSave = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) return;
    sessionStorage.setItem('ownerToken', token);
    window.location.reload();
  };

  const handleClear = () => {
    sessionStorage.removeItem('ownerToken');
    setToken('');
    setSaved(false);
  };

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
      {error && <ErrorAlert message={error} />}
      {notice && <p className="rounded border border-green-300 bg-green-50 p-3 text-sm text-green-800" role="status">{notice}</p>}

      {settings && form && (
        <form className="card p-6 space-y-6" onSubmit={handleSettingsSave}>
          <div>
            <h2 className="text-xl font-bold border-b border-border pb-2">Runtime policy</h2>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
              Financial values use integer cents. JSON controls are validated before the owner PATCH is sent.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {numericMeta.map((field) => (
              <div key={field.key}>
                <label className="block text-sm font-medium mb-1" htmlFor={field.key}>{field.label}</label>
                <input
                  id={field.key}
                  className="input-field"
                  type="number"
                  min={field.min}
                  max={'max' in field ? field.max : undefined}
                  step="1"
                  value={form[field.key]}
                  onChange={(event) => updateField(field.key, event.target.value)}
                  disabled={!saved || saving}
                />
              </div>
            ))}
          </div>
          <div>
            <h3 className="font-bold mb-3">Category, counterparty, domain, and rate controls</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {jsonMeta.map((field) => (
                <div key={field.key}>
                  <label className="block text-sm font-medium mb-1" htmlFor={field.key}>{field.label}</label>
                  <textarea
                    id={field.key}
                    className="input-field min-h-24 font-mono text-xs"
                    value={form[field.key]}
                    placeholder={field.example}
                    onChange={(event) => updateField(field.key, event.target.value)}
                    disabled={!saved || saving}
                    spellCheck={false}
                  />
                </div>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="btn-primary" disabled={!saved || saving}>
              {saving ? 'Saving…' : 'Save owner settings'}
            </button>
            {!saved && <span className="text-sm text-gray-500">Save an owner token below to edit settings.</span>}
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            Real money: <span className="font-bold text-red-600">{settings.real_money_enabled_stored ? 'UNSAFE LEGACY VALUE' : 'DISABLED'}</span>
            {settings.real_money_forced_off && ' (execution is forced off)'}
          </p>
        </form>
      )}

      <div className="card p-6">
        <h2 className="text-xl font-bold mb-4 border-b border-border pb-2">Owner Credentials</h2>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Actions requiring owner control (e.g., unfreeze, approve, and go/no-go) require a valid owner token.
          It is stored only in this tab&apos;s <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">sessionStorage</code> and never displayed.
        </p>
        <form onSubmit={handleTokenSave} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1" htmlFor="owner-token">Owner token</label>
            <input
              id="owner-token"
              type="password"
              className="input-field max-w-md"
              value={token}
              onChange={(event) => {
                setToken(event.target.value);
                if (saved) setSaved(false);
              }}
              placeholder={saved ? 'Token stored for this tab; enter a replacement' : 'Enter owner token'}
              required
            />
          </div>
          <div className="flex gap-2">
            <button type="submit" className="btn-primary">{saved ? 'Replace token' : 'Save in session'}</button>
            {saved && <button type="button" onClick={handleClear} className="btn-secondary">Clear token</button>}
          </div>
        </form>
      </div>
    </div>
  );
}
