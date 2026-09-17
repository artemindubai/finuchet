// Клиент REST-контракта ARCHITECTURE.md §5. Единственная точка, где фронт знает про сеть.
import type {
  AccountResponse, AnalyticsResponse, ApiError, Currency, DebtsResponse, EntriesPage, EntryDraft,
  EntryFull, EntryResult, Goal, HomeResponse, LimitRow, Money, PlannedItem, RatesResponse, Refs,
  SettingsResponse, ViewCurrency,
} from './types';

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === '1';
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
const DEV_USER = import.meta.env.VITE_DEV_USER as string | undefined;

export class RequestError extends Error {
  code: string;
  details?: Record<string, unknown>;
  constructor(e: ApiError) {
    super(e.message || e.code);
    this.code = e.code;
    this.details = e.details;
  }
}

function authHeaders(): Record<string, string> {
  const initData = (window as any).Telegram?.WebApp?.initData as string | undefined;
  if (initData) return { Authorization: `tma ${initData}` };
  if (DEV_USER) return { 'X-Dev-User': DEV_USER };
  return {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...authHeaders(),
      ...(init?.headers as Record<string, string> | undefined),
    },
  });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const e = body?.error ?? { code: 'network', message: 'Не удалось загрузить' };
    throw new RequestError(e);
  }
  return body as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

type MockServer = typeof import('../mocks/server');
let mockPromise: Promise<MockServer> | null = null;
function mocks(): Promise<MockServer> {
  if (!mockPromise) mockPromise = import('../mocks/server');
  return mockPromise;
}

export interface EntriesQuery {
  q?: string;
  account_id?: number;
  category_id?: number;
  kind?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  currency?: ViewCurrency;
  limit?: number;
  cursor?: string;
}

export const api = {
  async refs(): Promise<Refs> {
    if (USE_MOCKS) return (await mocks()).refs();
    return request<Refs>('/api/refs');
  },

  async home(currency: ViewCurrency = 'RUB'): Promise<HomeResponse> {
    if (USE_MOCKS) return (await mocks()).home(currency);
    return request<HomeResponse>(`/api/home${qs({ currency })}`);
  },

  async entries(query: EntriesQuery = {}): Promise<EntriesPage> {
    if (USE_MOCKS) return (await mocks()).entries(query);
    return request<EntriesPage>(`/api/entries${qs(query as Record<string, string | number | undefined>)}`);
  },

  async entry(id: number): Promise<EntryFull> {
    if (USE_MOCKS) return (await mocks()).entry(id);
    return request<EntryFull>(`/api/entries/${id}`);
  },

  async account(ref: number | string, query: { currency?: ViewCurrency; limit?: number; cursor?: string } = {}):
    Promise<AccountResponse> {
    if (USE_MOCKS) return (await mocks()).account(ref);
    return request<AccountResponse>(`/api/accounts/${ref}${qs(query)}`);
  },

  async analytics(month: string, currency: ViewCurrency = 'RUB'): Promise<AnalyticsResponse> {
    if (USE_MOCKS) return (await mocks()).analytics(month);
    return request<AnalyticsResponse>(`/api/analytics/month${qs({ month, currency })}`);
  },

  async categoryEntries(categoryId: number, month: string, currency: ViewCurrency = 'RUB', cursor?: string):
    Promise<{ items: EntriesPage['items']; total: Money; next_cursor: string | null; has_more: boolean }> {
    if (USE_MOCKS) return (await mocks()).categoryEntries(categoryId, month);
    return request(`/api/analytics/category${qs({ category_id: categoryId, month, currency, cursor })}`);
  },

  async debts(currency: ViewCurrency = 'RUB'): Promise<DebtsResponse> {
    if (USE_MOCKS) return (await mocks()).debts();
    return request<DebtsResponse>(`/api/debts${qs({ currency })}`);
  },

  async calendar(dateFrom: string, dateTo: string): Promise<{ items: PlannedItem[] }> {
    if (USE_MOCKS) return (await mocks()).calendar();
    return request(`/api/calendar${qs({ date_from: dateFrom, date_to: dateTo })}`);
  },

  async markPaid(id: number, body: { op_date?: string; amount?: number; account?: string | number }):
    Promise<{ planned: PlannedItem } & EntryResult> {
    if (USE_MOCKS) return (await mocks()).markPaid(id, body);
    return request(`/api/calendar/${id}/paid`, { method: 'POST', body: JSON.stringify(body) });
  },

  async goals(): Promise<{ items: Goal[] }> {
    if (USE_MOCKS) return (await mocks()).goals();
    return request('/api/goals');
  },

  async limits(month: string): Promise<{ items: LimitRow[] }> {
    if (USE_MOCKS) return (await mocks()).limits();
    return request(`/api/limits${qs({ month })}`);
  },

  async putLimit(categoryId: number, body: { amount: number; currency: Currency; active: boolean }):
    Promise<{ items: LimitRow[] }> {
    if (USE_MOCKS) return (await mocks()).putLimit(categoryId, body);
    return request(`/api/limits/${categoryId}`, { method: 'PUT', body: JSON.stringify(body) });
  },

  async rates(): Promise<RatesResponse> {
    if (USE_MOCKS) return (await mocks()).rates();
    return request<RatesResponse>('/api/rates');
  },

  async refreshRates(): Promise<RatesResponse> {
    if (USE_MOCKS) return (await mocks()).rates();
    return request<RatesResponse>('/api/rates/refresh', { method: 'POST' });
  },

  async settings(): Promise<SettingsResponse> {
    if (USE_MOCKS) return (await mocks()).settings();
    return request<SettingsResponse>('/api/settings');
  },

  async putSettings(patch: Partial<SettingsResponse> & Record<string, unknown>): Promise<SettingsResponse> {
    if (USE_MOCKS) return (await mocks()).putSettings(patch);
    return request<SettingsResponse>('/api/settings', { method: 'PUT', body: JSON.stringify(patch) });
  },

  async createEntry(draft: EntryDraft): Promise<EntryResult> {
    if (USE_MOCKS) return (await mocks()).createEntry(draft);
    return request<EntryResult>('/api/entries', { method: 'POST', body: JSON.stringify(draft) });
  },

  async voidEntry(id: number, reason?: string): Promise<EntryResult> {
    if (USE_MOCKS) return (await mocks()).setStatus(id, 'void');
    return request<EntryResult>(`/api/entries/${id}/void`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason ?? '' }),
    });
  },

  async unvoidEntry(id: number): Promise<EntryResult> {
    if (USE_MOCKS) return (await mocks()).setStatus(id, 'posted');
    return request<EntryResult>(`/api/entries/${id}/unvoid`, { method: 'POST' });
  },

  async amendEntry(id: number, patch: Partial<EntryDraft>): Promise<EntryResult> {
    if (USE_MOCKS) return (await mocks()).amendEntry(id, patch);
    return request<EntryResult>(`/api/entries/${id}/amend`, { method: 'POST', body: JSON.stringify(patch) });
  },

  async openingBalances(body: { op_date: string; items: { account: string; amount: number; currency: Currency }[] }):
    Promise<{ created: { entry_id: number; account: string }[] }> {
    if (USE_MOCKS) return (await mocks()).openingBalances(body);
    return request('/api/opening-balances', { method: 'POST', body: JSON.stringify(body) });
  },

  async exportXlsx(body: { period?: string; date_from?: string; date_to?: string; sheets?: string[] }):
    Promise<{ ok: boolean; delivery: string; message?: string; url?: string }> {
    if (USE_MOCKS) return (await mocks()).exportXlsx();
    return request('/api/export/xlsx', { method: 'POST', body: JSON.stringify(body) });
  },
};
