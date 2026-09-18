import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache, useResource } from '../app/data';
import { money, moneyWhole, num } from '../lib/format';
import { Button, Card, CardHead, Empty, LoadError, Screen } from '../components/ui';
import { DayBlock, TrancheRow } from '../components/rows';
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
          {/* Имя счёта уже стоит в шапке экрана — дважды в 100 px (m6). */}
          <div className="mt-1 text-[13px] text-hint">{CURRENCY_WORD[acc.currency] ?? acc.currency}</div>
        </div>

        {acc.frozen && acc.frozen.amount > 0 ? (
          <div className="mt-4">
            <Card>
              {/* При одном транше итог в шапке — то же число строкой ниже (m7). */}
              <CardHead
                title="Заморожено"
                action={
                  data.tranches.length > 1 ? (
                    <span className="nums text-[15px] font-medium">{moneyWhole(acc.frozen, 'none')}</span>
                  ) : undefined
                }
              />
              {data.tranches.length === 0 ? (
                <Empty text="Ничего не заморожено" />
              ) : (
                data.tranches.map((t) => <TrancheRow key={t.id} t={t} onClick={openEntry} />)
              )}
              {acc.free ? (
                <div className="nums pt-2 text-[13px] text-hint">свободно {moneyWhole(acc.free, 'none')}</div>
              ) : null}
            </Card>
          </div>
        ) : null}

        {/* Кнопки в ряд по 50 %: столбик из двух одинаковых серых плашек во всю ширину читался
            как «два варианта одного и того же» и съедал 200 CSS над лентой (M13). Карточка вокруг
            них — третья вложенная поверхность подряд, поэтому её нет. */}
        {/* Тексты полные, как в 4.4: «Выровнять» само по себе не говорит, что выравнивают (Н12). */}
        <div className="mt-4 flex gap-2">
          <span className="min-w-0 flex-1">
            <Button kind="secondary" onClick={() => setAlign(true)}>
              Выровнять остаток
            </Button>
          </span>
          <span className="min-w-0 flex-1">
            <Button kind="secondary" onClick={() => onAdd(acc.slug)}>
              Добавить операцию
            </Button>
          </span>
        </div>

        <div className="mt-6">
          {data.entries.items.length === 0 ? (
            <Card>
              <Empty text="По счёту пока пусто" />
            </Card>
          ) : (
            <Card>
              {data.entries.days.map((d, i) => (
                <DayBlock
                  key={d.date}
                  first={i === 0}
                  title={d.title}
                  total={d.total_out}
                  totalIn={d.total_in}
                  items={data.entries.items.filter((e) => d.ids.includes(e.id))}
                  onOpen={openEntry}
                />
              ))}
            </Card>
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
