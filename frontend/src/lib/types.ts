// Типы ответов API — строго по ARCHITECTURE.md §5. Поля не добавлять.

export type Currency = 'RUB' | 'AED' | 'USDT' | 'USD';
export type ViewCurrency = 'RUB' | 'USD' | 'AED';

export interface Money {
  amount: number; // целые минорные единицы
  currency: Currency;
}

export interface Warning {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface AccountView {
  id: number;
  slug: string;
  name: string;
  type: string;
  role: 'asset' | 'liability';
  currency: Currency;
  icon: string;
  balance: Money;
  natural: Money;
  in_view: Money;
  frozen: Money | null;
  free?: Money;
  archived: boolean;
}

export interface Group {
  key: string;
  title: string;
  total: Money;
  accounts: AccountView[];
}

export interface EntryShort {
  id: number;
  kind: string;
  direction: 'in' | 'out' | 'neutral';
  amount: Money;
  amount_in_view: Money;
  title: string;
  subtitle: string;
  category_id: number | null;
  icon: string;
  color: string;
  version: number;
  op_date: string;
  created_at: string;
  status: 'posted' | 'void';
  source: string;
  description: string;
  counterparty: string | null;
  project: string | null;
}

export interface Posting {
  seq: number;
  account_id: number;
  account_slug: string;
  account_name: string;
  side: 'debit' | 'credit';
  amount: Money;
  counterparty: string | null;
  project: string | null;
}

export interface TrancheView {
  id: number;
  op_date: string;
  aed_taken?: Money;
  aed_left: Money;
  rub_frozen?: Money;
  rub_left: Money;
  rate_e6: number;
  rate_source: string;
  account_id?: number;
  account_name?: string;
  entry_id?: number;
  status: string;
  label: string;
}

// В примере §5.5 у одной операции нет icon/color (они описаны только для ленты) —
// поэтому здесь они необязательные, а запасной вид берётся по kind (entryLook).
export interface EntryFull extends Omit<EntryShort, 'icon' | 'color'> {
  icon?: string;
  color?: string;
  replaces_entry_id: number | null;
  replaced_by_entry_id: number | null;
  voided_at?: string | null;
  void_reason?: string | null;
  due_date: string | null;
  raw_input: string | null;
  confidence: number | null;
  postings: Posting[];
  rate: { pair: string; rate_e6: number; source: string; at: string } | null;
  rates_snapshot: Record<string, unknown>;
  tranche: TrancheView | null;
  versions: { id: number; version: number; status: string; created_at: string; changed: string[] }[];
  warnings: Warning[];
}

export interface Effects {
  accounts: Pick<AccountView, 'id' | 'slug' | 'name' | 'role' | 'balance' | 'natural' | 'in_view' | 'frozen'>[];
  net_worth: Money;
  free_rub: Money;
  frozen_rub: Money;
  family_debt: Money;
  family_direction: string;
  tranche: TrancheView | null;
  released: { tranche_id: number; aed: Money; rub: Money }[];
}

export interface EntryResult extends EntryFull {
  effects: Effects;
}

export interface DayGroup {
  date: string;
  title: string;
  total_out: Money;
  total_in: Money;
  ids: number[];
}

export interface Breakdown {
  category_id?: number;
  source_id?: number;
  name: string;
  color: string;
  amount: Money;
  share_bp: number;
  icon?: string;   // есть у top_categories (§5.4) и у аналитики (§5.7), у summary ленты — нет
}

export interface EntriesPage {
  items: EntryShort[];
  days: DayGroup[];
  summary?: {
    currency: Currency;
    out: Money;
    in: Money;
    out_breakdown: Breakdown[];
    in_breakdown: Breakdown[];
  };
  next_cursor: string | null;
  has_more: boolean;
  total?: number;
}

export interface Upcoming {
  id: number;
  title: string;
  amount: Money;
  next_date: string;
  days_left: number;
  repeat: string;
  account_id: number | null;
  category_id: number | null;
  overdue: boolean;
}

export interface HomeResponse {
  currency: ViewCurrency;
  as_of: string;
  net_worth: Money;
  free_rub: Money;
  frozen_rub: Money;
  groups: Group[];
  totals_by_view: {
    net_worth: Record<ViewCurrency, Money>;
    groups: Record<string, Record<ViewCurrency, Money>>;
  };
  family: {
    visible: boolean;
    total: Money;
    accounts: AccountView[];
    debt: Money;
    direction: 'i_owe' | 'family_owes';
    frozen_rub: Money;
    frozen_note: string | null;
    today_repay_rub: Money | null;
  };
  upcoming: Upcoming[];
  recent: EntryShort[];
  month: {
    month: string;
    expense_total: Money;
    income_total: Money;
    top_categories: Breakdown[];
  };
  rates: {
    at: string;
    source: string;
    rub_per_aed_e6: number;
    rub_per_usd_e6: number;
    rub_per_usdt_e6: number;
  };
  warnings: Warning[];
}

export interface AccountResponse {
  account: AccountView;
  tranches: TrancheView[];
  entries: EntriesPage;
  month: { in: Money; out: Money };
}

export interface CategoryRow extends Breakdown {
  category_id: number;
  icon: string;
  count: number;
  prev_amount: Money;
  limit: Money | null;
  limit_used_bp: number | null;
}

export interface SourceRow extends Breakdown {
  source_id: number;
  icon: string;
  tax_accrued: Money | null;
  projects: { project: string; amount: Money; share_bp: number }[];
}

export interface LimitRow {
  category_id: number;
  name: string;
  limit: Money;
  spent: Money;
  used_bp: number;
  left_days: number;
}

export interface AnalyticsResponse {
  month: string;
  currency: ViewCurrency;
  prev_month: string | null;
  next_month: string | null;
  income_total: Money;
  expense_total: Money;
  net: Money;
  categories: CategoryRow[];
  by_month: { month: string; income: Money; expense: Money }[];
  income_sources: SourceRow[];
  limits: LimitRow[];
}

export interface DebtsResponse {
  owed_to_me: {
    counterparty_id: number;
    name: string;
    amounts: Money[];
    in_view: Money;
    due_date: string | null;
    since: string;
    entry_ids: number[];
  }[];
  i_owe: DebtsResponse['owed_to_me'];
  tax: { account_id: number; name: string; amount: Money; due_date: string | null; note: string };
  credit_card: { account_id: number; name: string; amount: Money; due_date: string | null };
  family: {
    debt: Money;
    direction: 'i_owe' | 'family_owes';
    frozen_rub: Money;
    today_repay_rub: Money | null;
    tranches: TrancheView[];
  };
  total_in_view: Money;
}

export interface PlannedItem extends Upcoming {
  day_of_month: number | null;
  remind_days_before: number;
  active: boolean;
  last_paid: { entry_id: number; op_date: string } | null;
}

export interface Goal {
  id: number;
  name: string;
  target: Money;
  saved: Money;
  progress_bp: number;
  due_date: string | null;
  account_id: number | null;
  allocations: { amount: Money; op_date: string; note: string }[];
}

export interface Refs {
  accounts: {
    id: number;
    slug: string;
    name: string;
    type: string;
    currency: Currency | null;
    is_money: boolean;
    group_key: string | null;
    icon: string;
    sort: number;
    archived: boolean;
  }[];
  categories: { id: number; slug: string; name: string; icon: string; color: string; sort: number; archived: boolean }[];
  income_sources: {
    id: number;
    slug: string;
    name: string;
    tax_rate_bp: number;
    tax_account_id: number;
    color: string;
    icon: string;
    sort: number;
    archived: boolean;
  }[];
  counterparties: { id: number; name: string; kind: string; archived: boolean }[];
  currencies: Currency[];
  kinds: { key: string; title: string }[];
}

export interface RatesResponse {
  at: string;
  rates: { pair: string; rate_e6: number; source: string; at: string; stale: boolean }[];
  markup_rub_per_aed_e6: number;
}

export interface SettingsResponse {
  default_currency_view: ViewCurrency;
  family_block_visible: boolean;
  freeze_account: string;
  rate_markup_rub_per_aed_e6: number;
  tax_rate_default_bp: number;
  remind_enabled: boolean;
  mashreq_pdf_password_set: boolean;
  stt_provider: string;
  version: string;
  db_size_bytes: number;
  last_backup_at: string;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

export interface EntryDraft {
  kind: string;
  amount: number;
  currency: Currency;
  from_account?: string | number | null;
  to_account?: string | number | null;
  category?: string | number | null;
  income_source?: string | number | null;
  counterparty?: string | null;
  project?: string | null;
  op_date?: string | null;
  description?: string;
}
