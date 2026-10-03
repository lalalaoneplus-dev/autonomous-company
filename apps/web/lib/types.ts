export type JsonObject = Record<string, unknown>;

export interface TreasurySnapshot {
  balance_cents: number;
  revenue_cents: number;
  expenses_cents: number;
  profit_cents: number;
  goal_reserve_cents?: number;
  currency?: string;
  unit?: string;
  frozen: boolean;
  real_money_enabled: boolean;
}

export interface SecurityEvent {
  id: string;
  severity: string;
  event_type: string;
  detail: JsonObject;
  froze_autonomy: boolean;
  created_at: string;
}

export interface SecurityState {
  frozen: boolean;
  freeze_reason: string | null;
  events: SecurityEvent[];
}

export interface SettingsData {
  autonomy_level: number;
  real_money_enabled: boolean;
  real_money_enabled_stored?: boolean;
  real_money_forced_off?: boolean;
  objective: string;
  strategy: string;
  owner_goal: string;
  limits: {
    global_spend_cents: number;
    per_transaction_cents: number;
    daily_spend_cents: number;
    approval_threshold_cents: number;
    model_cost_limit_cents: number;
    api_cost_limit_cents: number;
  };
  policy_controls: {
    category_allowlist: string[];
    category_denylist: string[];
    category_limits_cents: Record<string, number>;
    counterparty_allowlist: string[];
    counterparty_denylist: string[];
    domain_allowlist: string[];
    domain_denylist: string[];
    rate_limits: Record<string, unknown>;
  };
}

export interface PortfolioStream {
  opportunities: number;
  experiments: number;
  paper_revenue_cents: number;
  paper_cost_cents: number;
  pipeline_downside_cents: number;
  committed_risk_cents: number;
}

export interface PortfolioSnapshot {
  caps_bps: Record<string, number>;
  streams: Record<string, PortfolioStream>;
  metrics_are_paper_only: boolean;
  real_money_enabled: boolean;
}

export interface OverviewData {
  treasury: TreasurySnapshot;
  objective: string;
  owner_goal: string;
  autonomy_level: number;
  active_experiments: number;
  opportunities: number;
  pending_approvals: number;
  portfolio: PortfolioSnapshot;
  security: SecurityState;
  cycle_count: number;
  model_cost_cents: number;
}

export interface Approval {
  id: string;
  approval_class: string;
  requested_by: string;
  action_type: string;
  payload: JsonObject;
  reason: string;
  status: string;
  created_at: string;
}

export interface Agent {
  id: string;
  role: string;
  instructions: string;
  permissions: string[];
  active: boolean;
}

export interface Opportunity {
  id: string;
  title: string;
  category: string;
  stream_type: string;
  score_bps: number;
  source: string;
  status: string;
  demand_evidence_id?: string;
  expected_revenue_cents: number;
  max_downside_cents: number;
}

export interface DemandEvidence {
  id: string;
  source_url: string;
  source_platform: string;
  buyer_identity: string;
  captured_at: string;
  status_checked_at: string;
  quoted_need: string;
  stated_budget_cents: number | null;
  stated_currency: string | null;
  verification_status: string;
  external_content_untrusted: boolean;
}

export interface Negotiation {
  id: string;
  opportunity_id: string;
  state: string;
  mode: string;
  counterparty_identity: string;
  requested_product: string;
  scope: string;
  acceptance_criteria: string;
  agreed_price_cents: number | null;
  agreed_currency: string | null;
  counterparty_agreed: boolean;
  owner_go: boolean;
  owner_delivery_decision: 'PAPER' | 'REAL' | null;
}

export interface ProgramScope {
  id: string;
  program_url: string;
  assets_in_scope: string[];
  safe_harbor: string;
  status: string;
  owner_target_authorized: boolean;
  paper_outcome: boolean;
  captured_at: string;
}

export interface Experiment {
  id: string;
  title: string;
  hypothesis: string;
  stream_type: string;
  status: string;
  max_spend_cents: number;
  expenses_cents: number;
  revenue_cents: number;
  profit_cents: number;
  roi_bps: number;
  outcome_action?: string;
}

export interface Transaction {
  id: string;
  amount_cents: number;
  currency: string;
  debit_account?: string;
  credit_account?: string;
  external_reference?: string;
  description: string;
  status: string;
  created_at: string;
}

export interface AuditLog {
  id: string;
  created_at: string;
  actor: string;
  event_type: string;
  rationale: string;
  payload: JsonObject;
}

export interface Project {
  id: string;
  name: string;
  concept: string;
  customer_problem: string;
  audience: string;
  solution: string;
  price_cents: number;
  status: string;
  created_at: string;
}

export interface MemoryEntry {
  id: string;
  kind: string;
  tags: string[];
  content: JsonObject;
  created_at: string;
}

export interface ToolConfig {
  name: string;
  description: string;
  category: string;
  risk_class: string;
  required_autonomy_level: number;
  financial_exposure: boolean;
  approval_may_be_needed: boolean;
}

export interface CEOState {
  objective: string;
  owner_goal: string;
  strategy: string;
  autonomy_level: number;
  frozen: boolean;
  latest_experiment: Experiment | null;
}
