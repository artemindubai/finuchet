// Мок-сервер: повторяет ответы §5 по фикстурам. Включается только при VITE_USE_MOCKS=1.
// Живёт отдельным чанком — в прод-бандл не попадает.
import type {
  AccountResponse, AnalyticsResponse, Currency, DayGroup, DebtsResponse, EntriesPage, EntryDraft,
  EntryFull, EntryResult, Goal, HomeResponse, LimitRow, Money, PlannedItem, Posting, RatesResponse,
  Refs, SettingsResponse, ViewCurrency,
} from '../lib/types';
import type { EntriesQuery } from '../lib/api';

import homeRaw from './home.json';
import refsRaw from './refs.json';
import entriesRaw from './entries.json';
import entriesFullRaw from './entries_full.json';
import account5Raw from './account_5.json';
import analyticsSep from './analytics_2026-09.json';
import analyticsAug from './analytics_2026-08.json';
import debtsRaw from './debts.json';
import calendarRaw from './calendar.json';
import goalsRaw from './goals.json';
import limitsRaw from './limits.json';
import ratesRaw from './rates.json';
import settingsRaw from './settings.json';

const TODAY = '2026-09-17';

// Переключатели для съёмки состояний (M11). Только моки: ?slow=600 — скелетон успевает
// показаться, ?empty=1 — пустые списки, ?fail=1 — ошибка загрузки.
const FLAGS = (() => {
  try {
    const q = new URLSearchParams(window.location.search);
    return {
      delay: Number(q.get('slow')) || 120,
      empty: q.get('empty') === '1',
      fail: q.get('fail') === '1',
    };
  } catch {
    return { delay: 120, empty: false, fail: false };
  }
})();

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const wait = <T,>(v: T): Promise<T> =>
  new Promise((resolve, reject) => {
    setTimeout(() => {
      if (FLAGS.fail) reject({ code: 'network', message: 'Не удалось загрузить' });
      else resolve(v);
    }, FLAGS.delay);
  });

const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

interface EntryIndex { id: number; accounts: number[] }

const state = {
  home: clone(homeRaw) as unknown as HomeResponse,
  entries: clone((entriesRaw as any).items) as EntryFull[] as any[],
  index: ((entriesRaw as any)._index as EntryIndex[]).slice(),
  full: clone(entriesFullRaw) as Record<string, EntryFull>,
  settings: clone(settingsRaw) as unknown as SettingsResponse,
  limits: clone((limitsRaw as any).items) as LimitRow[],
  calendar: clone((calendarRaw as any).items) as PlannedItem[],
};

const RATE_E6: Record<Currency, number> = {
  RUB: 1_000_000,
  AED: state.home.rates.rub_per_aed_e6,
  USDT: state.home.rates.rub_per_usdt_e6,
  USD: state.home.rates.rub_per_usd_e6,
};

function rhu(num: number, den: number): number {
  return num >= 0 ? Math.floor((num + Math.floor(den / 2)) / den)
    : -Math.floor((-num + Math.floor(den / 2)) / den);
}
const toRub = (a: number, c: Currency) => rhu(a * RATE_E6[c], 1_000_000);
const fromRub = (a: number, c: ViewCurrency) => rhu(a * 1_000_000, RATE_E6[c]);
const money = (amount: number, currency: Currency): Money => ({ amount, currency });

/** Итог = Σ групп + постоянная часть (долги, налог, долг семье) — она в моках не меняется. */
const EXTRAS = state.home.net_worth.amount - state.home.groups.reduce((s, g) => s + g.total.amount, 0);

function recalcHome() {
  const h = state.home;
  for (const g of h.groups) {
    for (const a of g.accounts) {
      a.in_view = money(a.balance.amount === 0 ? 0 : toRub(a.balance.amount, a.balance.currency), 'RUB');
      a.natural = money(a.role === 'liability' ? -a.balance.amount : a.balance.amount, a.balance.currency);
    }
    g.total = money(g.accounts.reduce((s, a) => s + a.in_view.amount, 0), 'RUB');
  }
  h.net_worth = money(h.groups.reduce((s, g) => s + g.total.amount, 0) + EXTRAS, 'RUB');
  const rubAccounts = h.groups.find((g) => g.key === 'RUB')?.accounts ?? [];
  const rubTotal = rubAccounts.filter((a) => a.role === 'asset').reduce((s, a) => s + a.balance.amount, 0);
  h.free_rub = money(rubTotal - h.frozen_rub.amount, 'RUB');
  for (const c of ['RUB', 'USD', 'AED'] as ViewCurrency[]) {
    h.totals_by_view.net_worth[c] = money(fromRub(h.net_worth.amount, c), c);
    for (const g of h.groups) h.totals_by_view.groups[g.key][c] = money(fromRub(g.total.amount, c), c);
  }
}

function accountById(id: number) {
  for (const g of state.home.groups) {
    const a = g.accounts.find((x) => x.id === id);
    if (a) return a;
  }
  return state.home.family.accounts.find((x) => x.id === id) ?? null;
}

function applyPostings(postings: Posting[], sign: 1 | -1) {
  for (const p of postings) {
    const acc = accountById(p.account_id);
    if (!acc) continue;
    const delta = (p.side === 'debit' ? 1 : -1) * p.amount.amount * sign;
    acc.balance = money(acc.balance.amount + delta, acc.balance.currency);
  }
  recalcHome();
}

function dayTitle(date: string): string {
  if (date === TODAY) return 'Сегодня';
  const d = new Date(`${date}T00:00:00Z`);
  const today = new Date(`${TODAY}T00:00:00Z`);
  if ((today.getTime() - d.getTime()) / 86400000 === 1) return 'Вчера';
  const [, mm, dd] = date.split('-');
  return `${Number(dd)} ${MONTHS_GEN[Number(mm) - 1]}`;
}

function buildDays(items: any[]): DayGroup[] {
  const map = new Map<string, DayGroup>();
  for (const e of items) {
    let d = map.get(e.op_date);
    if (!d) {
      d = {
        date: e.op_date, title: dayTitle(e.op_date),
        total_out: money(0, 'RUB'), total_in: money(0, 'RUB'), ids: [],
      };
      map.set(e.op_date, d);
    }
    d.ids.push(e.id);
    if (e.status === 'void') continue;
    if (e.direction === 'out') d.total_out.amount += e.amount_in_view.amount;
    if (e.direction === 'in') d.total_in.amount += e.amount_in_view.amount;
  }
  return [...map.values()];
}

function monthOf(date: string) { return date.slice(0, 7); }

function analyticsFor(month: string): AnalyticsResponse {
  const src = month === '2026-08' ? analyticsAug : analyticsSep;
  return clone(src) as unknown as AnalyticsResponse;
}

function summaryFor(month: string, items: any[], narrowed: boolean): EntriesPage['summary'] {
  if (!narrowed) {
    const a = analyticsFor(month);
    return {
      currency: 'RUB',
      out: a.expense_total,
      in: a.income_total,
      out_breakdown: a.categories.slice(0, 6).map((c) => ({
        category_id: c.category_id, name: c.name, color: c.color, amount: c.amount, share_bp: c.share_bp,
      })),
      in_breakdown: a.income_sources.map((s) => ({
        source_id: s.source_id, name: s.name, color: s.color, amount: s.amount, share_bp: s.share_bp,
      })),
    };
  }
  const out = items.filter((e) => e.direction === 'out' && e.status === 'posted');
  const inc = items.filter((e) => e.direction === 'in' && e.status === 'posted');
  const sum = (list: any[]) => list.reduce((s, e) => s + e.amount_in_view.amount, 0);
  const group = (list: any[], key: 'category_id') => {
    const m = new Map<number, { name: string; color: string; amount: number }>();
    for (const e of list) {
      const id = e[key] ?? 0;
      const cur = m.get(id) ?? { name: e.title, color: e.color, amount: 0 };
      cur.amount += e.amount_in_view.amount;
      m.set(id, cur);
    }
    const total = sum(list) || 1;
    return [...m.entries()]
      .sort((a, b) => b[1].amount - a[1].amount)
      .slice(0, 6)
      .map(([id, v]) => ({
        category_id: id, name: v.name, color: v.color,
        amount: money(v.amount, 'RUB'), share_bp: Math.round((v.amount * 10000) / total),
      }));
  };
  return {
    currency: 'RUB', out: money(sum(out), 'RUB'), in: money(sum(inc), 'RUB'),
    out_breakdown: group(out, 'category_id'), in_breakdown: group(inc, 'category_id'),
  };
}

// ---------- публичный «API» ----------

export function refs(): Promise<Refs> {
  return wait(clone(refsRaw) as unknown as Refs);
}

export function home(currency: ViewCurrency): Promise<HomeResponse> {
  const h = clone(state.home);
  h.currency = currency;
  h.net_worth = h.totals_by_view.net_worth[currency];
  h.recent = state.entries.filter((e) => e.status === 'posted').slice(0, 7);
  return wait(h);
}

export function entries(q: EntriesQuery): Promise<EntriesPage> {
  if (FLAGS.empty) {
    return wait({ items: [], days: [], next_cursor: null, has_more: false, total: 0 } as EntriesPage);
  }
  const status = q.status ?? 'posted';
  const accountIds = new Map(state.index.map((i) => [i.id, i.accounts]));
  let items = state.entries.filter((e) => {
    if (status !== 'all' && e.status !== status) return false;
    if (q.date_from && e.op_date < q.date_from) return false;
    if (q.date_to && e.op_date > q.date_to) return false;
    if (q.account_id && !(accountIds.get(e.id) ?? []).includes(q.account_id)) return false;
    if (q.category_id && e.category_id !== q.category_id) return false;
    if (q.kind && e.kind !== q.kind) return false;
    if (q.q) {
      const hay = `${e.title} ${e.subtitle} ${e.description} ${e.counterparty ?? ''} ${e.project ?? ''}`.toLowerCase();
      if (!hay.includes(q.q.toLowerCase())) return false;
    }
    return true;
  });
  const narrowed = Boolean(q.account_id || q.category_id || q.kind || q.q);
  const total = items.length;
  const limit = q.limit ?? 30;
  const start = q.cursor ? Number(atob(q.cursor)) : 0;
  const page = items.slice(start, start + limit);
  const hasMore = start + limit < total;
  const res: EntriesPage = {
    items: page,
    days: buildDays(page),
    next_cursor: hasMore ? btoa(String(start + limit)) : null,
    has_more: hasMore,
    total,
  };
  if (!q.cursor) {
    res.summary = summaryFor(monthOf(q.date_from ?? TODAY), items, narrowed);
  }
  return wait(res);
}

export function entry(id: number): Promise<EntryFull> {
  const f = state.full[String(id)];
  if (!f) return Promise.reject({ code: 'not_found', message: 'Операция не найдена' });
  const short = state.entries.find((e) => e.id === id);
  const merged = clone(f);
  if (short) merged.status = short.status;
  return wait(merged);
}

export function account(ref: number | string): Promise<AccountResponse> {
  const accountIds = new Map(state.index.map((i) => [i.id, i.accounts]));
  const base = clone(account5Raw) as unknown as AccountResponse;
  const id = typeof ref === 'number' ? ref : Number(ref);
  const acc = accountById(id);
  if (!acc || id === base.account.id) {
    const items = state.entries.filter((e) => (accountIds.get(e.id) ?? []).includes(base.account.id));
    base.account = { ...base.account, ...(accountById(base.account.id) ?? {}) } as AccountResponse['account'];
    base.account.free = money(base.account.balance.amount - (base.account.frozen?.amount ?? 0), 'RUB');
    base.entries = { items, days: buildDays(items), next_cursor: null, has_more: false };
    return wait(base);
  }
  const items = state.entries.filter((e) => (accountIds.get(e.id) ?? []).includes(id));
  const monthItems = items.filter((e) => e.op_date >= '2026-09-01' && e.status === 'posted');
  return wait({
    account: { ...acc, free: undefined } as AccountResponse['account'],
    tranches: [],
    entries: { items, days: buildDays(items), next_cursor: null, has_more: false },
    month: {
      in: money(monthItems.filter((e) => e.direction === 'in').reduce((s, e) => s + e.amount_in_view.amount, 0), 'RUB'),
      out: money(monthItems.filter((e) => e.direction === 'out').reduce((s, e) => s + e.amount_in_view.amount, 0), 'RUB'),
    },
  });
}

export function analytics(month: string): Promise<AnalyticsResponse> {
  return wait(analyticsFor(month));
}

export function categoryEntries(categoryId: number, month: string):
  Promise<{ items: any[]; total: Money; next_cursor: null; has_more: false }> {
  const items = state.entries.filter(
    (e) => e.category_id === categoryId && e.status === 'posted' && monthOf(e.op_date) === month,
  );
  return wait({
    items,
    total: money(items.reduce((s, e) => s + e.amount_in_view.amount, 0), 'RUB'),
    next_cursor: null,
    has_more: false,
  });
}

export function debts(): Promise<DebtsResponse> {
  return wait(clone(debtsRaw) as unknown as DebtsResponse);
}

export function calendar(): Promise<{ items: PlannedItem[] }> {
  return wait({ items: clone(state.calendar) });
}

export function goals(): Promise<{ items: Goal[] }> {
  return wait(clone(goalsRaw) as unknown as { items: Goal[] });
}

export function limits(): Promise<{ items: LimitRow[] }> {
  return wait({ items: clone(state.limits) });
}

export function putLimit(categoryId: number, body: { amount: number; currency: Currency; active: boolean }):
  Promise<{ items: LimitRow[] }> {
  const row = state.limits.find((l) => l.category_id === categoryId);
  if (row) {
    row.limit = money(body.amount, body.currency);
    row.used_bp = rhu(row.spent.amount * 10000, body.amount || 1);
  }
  return wait({ items: clone(state.limits) });
}

export function rates(): Promise<RatesResponse> {
  return wait(clone(ratesRaw) as unknown as RatesResponse);
}

export function settings(): Promise<SettingsResponse> {
  return wait(clone(state.settings));
}

export function putSettings(patch: Record<string, unknown>): Promise<SettingsResponse> {
  Object.assign(state.settings, patch);
  if ('family_block_visible' in patch) state.home.family.visible = Boolean(patch.family_block_visible);
  return wait(clone(state.settings));
}

function effects(): EntryResult['effects'] {
  return {
    accounts: [],
    net_worth: state.home.net_worth,
    free_rub: state.home.free_rub,
    frozen_rub: state.home.frozen_rub,
    family_debt: state.home.family.debt,
    family_direction: state.home.family.direction,
    tranche: null,
    released: [],
  };
}

export function setStatus(id: number, status: 'posted' | 'void'): Promise<EntryResult> {
  const short = state.entries.find((e) => e.id === id);
  const full = state.full[String(id)];
  if (!short || !full) return Promise.reject({ code: 'not_found', message: 'Операция не найдена' });
  if (short.status === status) {
    return Promise.reject({
      code: status === 'void' ? 'already_void' : 'not_voided',
      message: 'Состояние уже такое',
    });
  }
  short.status = status;
  full.status = status;
  applyPostings(full.postings, status === 'void' ? -1 : 1);
  return wait({ ...clone(full), effects: effects() } as EntryResult);
}

const SLUG_BY_ID = new Map<number, string>(
  [...(refsRaw as any).accounts, ...(refsRaw as any).categories, ...(refsRaw as any).income_sources]
    .map((a: any) => [a.id, a.slug]),
);
const REF_BY_SLUG = new Map<string, any>(
  [...(refsRaw as any).accounts, ...(refsRaw as any).categories, ...(refsRaw as any).income_sources]
    .map((a: any) => [a.slug, a]),
);
void SLUG_BY_ID;

export function createEntry(draft: EntryDraft): Promise<EntryResult> {
  const id = Math.max(...state.entries.map((e) => e.id)) + 1;
  const opDate = draft.op_date ?? TODAY;
  const from = draft.from_account ? REF_BY_SLUG.get(String(draft.from_account)) : null;
  const to = draft.to_account ? REF_BY_SLUG.get(String(draft.to_account)) : null;
  const cat = draft.category ? REF_BY_SLUG.get(String(draft.category)) : null;
  const src = draft.income_source ? REF_BY_SLUG.get(String(draft.income_source)) : null;
  const cur = draft.currency;
  const postings: Posting[] = [];
  const push = (ref: any, side: 'debit' | 'credit') => {
    postings.push({
      seq: postings.length + 1, account_id: ref.id, account_slug: ref.slug, account_name: ref.name,
      side, amount: money(draft.amount, cur), counterparty: null, project: null,
    });
  };
  let title = '';
  let subtitle = '';
  let icon = 'dots';
  let color = '#A0A7B0';
  let direction: 'in' | 'out' | 'neutral' = 'neutral';
  if (draft.kind === 'expense' && cat && from) {
    push(cat, 'debit'); push(from, 'credit');
    title = cat.name; subtitle = from.name; icon = cat.icon; color = cat.color; direction = 'out';
  } else if (draft.kind === 'income' && src && to) {
    push(to, 'debit'); push(src, 'credit');
    title = src.name; subtitle = to.name; icon = src.icon; color = src.color; direction = 'in';
  } else if (from && to) {
    push(to, 'debit'); push(from, 'credit');
    const isFamily = draft.kind.startsWith('family');
    title = isFamily ? (draft.kind === 'family_withdrawal' ? 'Взял из семейного' : 'Вернул в семейный') : 'Перевод';
    subtitle = `${from.name} → ${to.name}`;
    icon = isFamily ? 'family' : 'swap';
    color = isFamily ? '#34B37E' : '#7B8794';
  } else {
    return Promise.reject({ code: 'bad_request', message: 'Не хватает счёта' });
  }
  const created = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const short: any = {
    id, kind: draft.kind, direction, amount: money(draft.amount, cur),
    amount_in_view: money(toRub(draft.amount, cur), 'RUB'),
    title, subtitle, category_id: cat?.id ?? src?.id ?? null, icon, color, version: 1,
    op_date: opDate, created_at: created, status: 'posted', source: 'manual',
    description: draft.description ?? '', counterparty: null, project: null,
  };
  const full: EntryFull = {
    ...short,
    replaces_entry_id: null, replaced_by_entry_id: null, due_date: null,
    raw_input: null, confidence: null, postings,
    rate: null, rates_snapshot: {}, tranche: null,
    versions: [{ id, version: 1, status: 'posted', created_at: created, changed: [] }],
    warnings: [],
  };
  state.entries.unshift(short);
  state.entries.sort((a, b) => (a.op_date === b.op_date ? b.id - a.id : a.op_date < b.op_date ? 1 : -1));
  state.index.push({ id, accounts: postings.map((p) => p.account_id) });
  state.full[String(id)] = full;
  applyPostings(postings, 1);
  return wait({ ...clone(full), effects: effects() } as EntryResult);
}

export function amendEntry(id: number, patch: Partial<EntryDraft>): Promise<EntryResult> {
  const short = state.entries.find((e) => e.id === id);
  const full = state.full[String(id)];
  if (!short || !full) return Promise.reject({ code: 'not_found', message: 'Операция не найдена' });
  if (patch.amount) {
    applyPostings(full.postings, -1);
    for (const p of full.postings) p.amount = money(patch.amount, p.amount.currency);
    short.amount = money(patch.amount, short.amount.currency);
    short.amount_in_view = money(toRub(patch.amount, short.amount.currency), 'RUB');
    full.amount = short.amount;
    full.amount_in_view = short.amount_in_view;
    applyPostings(full.postings, 1);
  }
  if (patch.description !== undefined) {
    short.description = patch.description;
    full.description = patch.description;
  }
  short.version += 1;
  full.version = short.version;
  full.versions.push({
    id, version: short.version, status: 'posted',
    created_at: new Date().toISOString(), changed: ['сумма исправлена'],
  });
  return wait({ ...clone(full), effects: effects() } as EntryResult);
}

export function markPaid(id: number, body: { op_date?: string; amount?: number; account?: string | number }):
  Promise<any> {
  const planned = state.calendar.find((p) => p.id === id);
  if (!planned) return Promise.reject({ code: 'not_found', message: 'Платёж не найден' });
  planned.last_paid = { entry_id: 0, op_date: body.op_date ?? TODAY };
  return wait({ planned: clone(planned), effects: effects() });
}

export function openingBalances(body: { op_date: string; items: { account: string; amount: number; currency: Currency }[] }):
  Promise<{ created: { entry_id: number; account: string }[] }> {
  return wait({ created: body.items.map((i, n) => ({ entry_id: 900 + n, account: i.account })) });
}

export function exportXlsx(): Promise<{ ok: boolean; delivery: string; message: string }> {
  return wait({ ok: true, delivery: 'bot', message: 'Файл придёт в чат' });
}
