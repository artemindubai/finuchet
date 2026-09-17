import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache, useResource } from '../app/data';
import { money, num } from '../lib/format';
import { Button, Card, CardHead, Empty, LoadError, Screen } from '../components/ui';
import { EntryRow, TrancheRow } from '../components/rows';
import { FeedSkeleton } from '../components/Skeleton';
import { Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { back, openEntry } from '../app/router';
import { haptic } from '../app/telegram';
import type { AccountResponse } from '../lib/types';

const CURRENCY_WORD: Record<string, string> = {
  RUB: 'рубли',
  AED: 'дирхамы',
  USDT: 'USDT',
  USD: 'доллары',
};

export function Account({ id, onAdd }: { id: number; onAdd: (slug: string) => void }) {
  const { data, error, loading, reload } = useResource<AccountResponse>(`account:${id}`, () => api.account(id));
  const [align, setAlign] = useState(false);
  const [factText, setFactText] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const header = (title: string) => (
    <div className="sticky top-0 z-20 -mx-4 mb-1 flex h-[52px] items-center bg-bg px-4">
      <button
        type="button"
        aria-label="Назад"
        className="flex h-11 w-11 items-center justify-center"
        onClick={() => {
          haptic.tap();
          back();
        }}
      >
        <ChevronLeft size={24} />
      </button>
      <div className="flex-1 truncate text-center text-[17px] font-semibold">{title}</div>
      <div className="w-11" />
    </div>
  );

  if (loading) {
    return (
      <Screen>
        {header('Счёт')}
        <span className="skeleton skeleton-wrap mt-4 block h-10 w-48" />
        <div className="mt-6">
          <FeedSkeleton />
        </div>
      </Screen>
    );
  }
  if (error || !data) {
    return (
      <Screen>
        {header('Счёт')}
        <LoadError onRetry={reload} />
      </Screen>
    );
  }

  const acc = data.account;
  const shown = acc.role === 'liability' ? acc.natural : acc.balance;

  const submitAlign = async () => {
    const minor = Math.round(Number(factText.replace(',', '.').replace(/\s/g, '')) * 100);
    if (!Number.isFinite(minor)) return;
    const delta = minor - acc.balance.amount;
    if (delta === 0) {
      setAlign(false);
      toast({ text: 'Уже сходится' });
      return;
    }
    setBusy(true);
    try {
      // Корреспондента ядро выбирает само (§4.2): eq_correction, а для семейного счёта — family_fund.
      await api.createEntry({
        kind: 'balance_correction',
        amount: delta,
        currency: acc.currency,
        to_account: acc.slug,
      });
      dropCache('home');
      dropCache('entries');
      dropCache('account');
      haptic.success();
      toast({ text: 'Остаток выровнен' });
      setAlign(false);
      reload();
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Screen>
        {header(acc.name)}

        <div className="pt-2">
          <div className="nums text-[34px] font-bold leading-10 tracking-[-0.02em]">{money(shown, 'none')}</div>
          <div className="mt-1 text-[13px] text-hint">
            {acc.name} · {CURRENCY_WORD[acc.currency] ?? acc.currency}
          </div>
        </div>

        {acc.frozen && acc.frozen.amount > 0 ? (
          <div className="mt-4">
            <Card>
              <CardHead
                title="Заморожено"
                action={<span className="nums text-[15px] font-medium">{money(acc.frozen, 'none')}</span>}
              />
              {data.tranches.length === 0 ? (
                <Empty text="Ничего не заморожено" />
              ) : (
                data.tranches.map((t) => <TrancheRow key={t.id} t={t} onClick={openEntry} />)
              )}
              {acc.free ? (
                <div className="nums pt-2 text-[13px] text-hint">свободно {money(acc.free, 'none')}</div>
              ) : null}
            </Card>
          </div>
        ) : null}

        <div className="mt-3">
          <Card>
            <div className="flex flex-col gap-2">
              <Button kind="secondary" onClick={() => setAlign(true)}>
                Выровнять остаток
              </Button>
              <Button kind="secondary" onClick={() => onAdd(acc.slug)}>
                Добавить операцию
              </Button>
            </div>
          </Card>
        </div>

        <div className="mt-6">
          {data.entries.items.length === 0 ? (
            <Card>
              <Empty text="По счёту пока пусто" />
            </Card>
          ) : (
            data.entries.days.map((d) => (
              <section key={d.date} className="mb-3">
                <div className="mb-1 flex items-baseline justify-between px-1">
                  <h2 className="text-[15px] font-bold leading-5">{d.title}</h2>
                  {d.total_out.amount > 0 ? (
                    <span className="nums text-[15px] leading-5 text-hint">{money(d.total_out, 'minus')}</span>
                  ) : null}
                </div>
                <Card>
                  {data.entries.items
                    .filter((e) => d.ids.includes(e.id))
                    .map((e) => (
                      <EntryRow key={e.id} e={e} onClick={openEntry} />
                    ))}
                </Card>
              </section>
            ))
          )}
        </div>
      </Screen>

      {align ? (
        <Sheet
          title="Выровнять остаток"
          onClose={() => setAlign(false)}
          footer={
            <Button onClick={submitAlign} loading={busy}>
              Выровнять
            </Button>
          }
        >
          <div className="flex h-[60px] items-center gap-2 rounded-inset bg-inset px-4">
            <input
              autoFocus
              inputMode="decimal"
              className="nums w-full text-[28px] font-semibold"
              placeholder={num(acc.balance.amount)}
              value={factText}
              onChange={(e) => setFactText(e.target.value)}
            />
            <span className="text-[17px] text-hint">{acc.currency}</span>
          </div>
          <div className="nums mt-2 text-[13px] text-hint">В учёте {money(acc.balance, 'none')}</div>
        </Sheet>
      ) : null}
    </>
  );
}
