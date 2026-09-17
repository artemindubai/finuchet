import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Search } from 'lucide-react';
import { api } from '../lib/api';
import type { EntriesQuery } from '../lib/api';
import { useResource } from '../app/data';
import { money, monthLong } from '../lib/format';
import { Card, Chip, Empty, LoadError, Screen } from '../components/ui';
import { EntryRow } from '../components/rows';
import { ShareBar } from '../components/Charts';
import { FeedSkeleton } from '../components/Skeleton';
import { PickerLayer } from '../components/Sheet';
import { openEntry } from '../app/router';
import { currentMonth, monthEnd, recentMonths } from '../lib/today';
import { haptic } from '../app/telegram';
import type { EntriesPage, EntryShort, Refs } from '../lib/types';

function monthBounds(month: string) {
  return { from: `${month}-01`, to: monthEnd(month) };
}

type PickerKind = 'month' | 'account' | 'category' | 'kind' | null;

export function Entries({ onAdd }: { onAdd: () => void }) {
  const [month, setMonth] = useState<string | null>(currentMonth());
  const [accountId, setAccountId] = useState<number | null>(null);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [picker, setPicker] = useState<PickerKind>(null);

  const refs = useResource<Refs>('refs', () => api.refs());

  const filters: EntriesQuery = useMemo(() => {
    const f: EntriesQuery = { limit: 30 };
    if (month) {
      const b = monthBounds(month);
      f.date_from = b.from;
      f.date_to = b.to;
    }
    if (accountId) f.account_id = accountId;
    if (categoryId) f.category_id = categoryId;
    if (kind) f.kind = kind;
    if (query.trim()) f.q = query.trim();
    return f;
  }, [month, accountId, categoryId, kind, query]);

  const key = `entries:${JSON.stringify(filters)}`;
  const first = useResource<EntriesPage>(key, () => api.entries(filters));
  const [extra, setExtra] = useState<EntryShort[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setExtra([]);
    setCursor(first.data?.next_cursor ?? null);
  }, [key, first.data]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    const page = await api.entries({ ...filters, cursor });
    setExtra((prev) => [...prev, ...page.items]);
    setCursor(page.next_cursor);
    setLoadingMore(false);
  }, [cursor, filters, loadingMore]);

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !cursor) return;
    const io = new IntersectionObserver((rows) => {
      if (rows[0]?.isIntersecting) void loadMore();
    }, { rootMargin: '200px' });
    io.observe(node);
    return () => io.disconnect();
  }, [cursor, loadMore]);

  const items = useMemo(() => [...(first.data?.items ?? []), ...extra], [first.data, extra]);
  const days = useMemo(() => {
    const byDate = new Map<string, EntryShort[]>();
    for (const e of items) {
      const list = byDate.get(e.op_date) ?? [];
      list.push(e);
      byDate.set(e.op_date, list);
    }
    const titles = new Map((first.data?.days ?? []).map((d) => [d.date, d]));
    return [...byDate.entries()].map(([date, list]) => ({
      date,
      meta: titles.get(date),
      list,
    }));
  }, [items, first.data]);

  const clearAll = () => {
    setAccountId(null);
    setCategoryId(null);
    setKind(null);
  };

  const accounts = refs.data?.accounts.filter((a) => !a.archived) ?? [];
  const categories = refs.data?.categories ?? [];
  const kinds = refs.data?.kinds ?? [];

  const months = recentMonths(4);

  return (
    <>
      <Screen>
        <div className="sticky top-0 z-20 -mx-4 flex h-[52px] items-center gap-2 bg-bg px-4">
          <h1 className="flex-1 text-[22px] font-bold leading-7 tracking-[-0.01em]">Операции</h1>
          <button
            type="button"
            aria-label="Поиск"
            className="flex h-11 w-11 items-center justify-center"
            onClick={() => {
              haptic.tap();
              setSearchOpen((v) => !v);
            }}
          >
            <Search size={22} strokeWidth={1.8} className={searchOpen ? 'text-blue' : 'text-text'} />
          </button>
          <button
            type="button"
            aria-label="Добавить операцию"
            className="flex h-11 w-11 items-center justify-center"
            onClick={() => {
              haptic.tap();
              onAdd();
            }}
          >
            <Plus size={24} strokeWidth={2} />
          </button>
        </div>

        {searchOpen ? (
          <input
            autoFocus
            className="mb-3 h-11 w-full rounded-full bg-inset px-4 text-[16px] placeholder:text-hint"
            placeholder="Поиск"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        ) : null}

        <div className="no-scrollbar -mx-4 mb-3 flex gap-2 overflow-x-auto px-4">
          <Chip active={Boolean(month)} onClick={() => setPicker('month')} onClear={() => setMonth(null)}>
            {month ? monthLong(month).split(' ')[0] : 'Период'}
          </Chip>
          <Chip
            active={Boolean(accountId)}
            onClick={() => setPicker('account')}
            onClear={() => setAccountId(null)}
          >
            {accountId ? accounts.find((a) => a.id === accountId)?.name ?? 'Счёт' : 'Счета'}
          </Chip>
          <Chip
            active={Boolean(categoryId)}
            onClick={() => setPicker('category')}
            onClear={() => setCategoryId(null)}
          >
            {categoryId ? categories.find((c) => c.id === categoryId)?.name ?? 'Категория' : 'Категории'}
          </Chip>
          <Chip active={Boolean(kind)} onClick={() => setPicker('kind')} onClear={() => setKind(null)}>
            {kind ? kinds.find((k) => k.key === kind)?.title ?? 'Тип' : 'Тип'}
          </Chip>
        </div>

        {first.data?.summary ? (
          <div className="mb-3 grid grid-cols-2 gap-3">
            <div className="rounded-card bg-card p-4">
              <div className="nums text-[20px] font-bold leading-6">{money(first.data.summary.out, 'none')}</div>
              <div className="mb-3 mt-0.5 text-[15px] text-hint">Траты</div>
              <ShareBar parts={first.data.summary.out_breakdown} />
            </div>
            <div className="rounded-card bg-card p-4">
              <div className="nums text-[20px] font-bold leading-6">{money(first.data.summary.in, 'none')}</div>
              <div className="mb-3 mt-0.5 text-[15px] text-hint">Доходы</div>
              <ShareBar parts={first.data.summary.in_breakdown} />
            </div>
          </div>
        ) : null}

        {first.loading ? (
          <FeedSkeleton />
        ) : first.error ? (
          <LoadError onRetry={first.reload} />
        ) : items.length === 0 ? (
          <Card>
            <Empty text={query ? 'Ничего не нашлось' : accountId || categoryId || kind ? 'Под фильтр ничего не попало' : 'Операций пока нет'} />
            {(accountId || categoryId || kind) && !query ? (
              <div className="pb-2 pt-4 text-center">
                <button type="button" className="text-[15px] font-medium text-blue" onClick={clearAll}>
                  Сбросить фильтры
                </button>
              </div>
            ) : null}
          </Card>
        ) : (
          days.map((d) => (
            <section key={d.date} className="mb-3">
              <div className="mb-1 flex items-baseline justify-between px-1">
                <h2 className="text-[15px] font-bold leading-5">{d.meta?.title ?? d.date}</h2>
                {d.meta && d.meta.total_out.amount > 0 ? (
                  <span className="nums text-[15px] leading-5 text-hint">
                    {money(d.meta.total_out, 'minus')}
                  </span>
                ) : null}
              </div>
              <Card>
                {d.list.map((e) => (
                  <EntryRow key={e.id} e={e} onClick={openEntry} />
                ))}
              </Card>
            </section>
          ))
        )}

        <div ref={sentinel} />
        {cursor ? <FeedSkeleton rows={3} /> : null}
      </Screen>

      {picker === 'month' ? (
        <PickerLayer
          title="Период"
          options={months.map((mo) => ({ value: mo, label: monthLong(mo) }))}
          value={month}
          onPick={(v) => {
            setMonth(v);
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
      {picker === 'account' ? (
        <PickerLayer
          title="Счёт"
          search
          options={accounts.map((a) => ({ value: String(a.id), label: a.name, hint: a.currency ?? undefined }))}
          value={accountId ? String(accountId) : null}
          onPick={(v) => {
            setAccountId(Number(v));
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
      {picker === 'category' ? (
        <PickerLayer
          title="Категория"
          search
          options={categories.map((c) => ({ value: String(c.id), label: c.name }))}
          value={categoryId ? String(categoryId) : null}
          onPick={(v) => {
            setCategoryId(Number(v));
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
      {picker === 'kind' ? (
        <PickerLayer
          title="Тип операции"
          options={kinds.map((k) => ({ value: k.key, label: k.title }))}
          value={kind}
          onPick={(v) => {
            setKind(v);
            setPicker(null);
          }}
          onClose={() => setPicker(null)}
        />
      ) : null}
    </>
  );
}
