import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache, useResource } from '../app/data';
import { dateLong, money, moneyWhole, num } from '../lib/format';
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
  // 'fact' — ввод пересчёта для сверки (29.09): то же поле, но ядро ещё запоминает факт.
  const [alignMode, setAlignMode] = useState<'align' | 'fact'>('align');
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
  // 29.09 Артём: кредитка — минусом, как долг, а не положительным числом.
  const liability = acc.role === 'liability';
  const shown = acc.balance;
  const check = data.check ?? null;
  const kop = data.kopilka ?? null;

  const submitAlign = async () => {
    const minor = Math.round(Number(factText.replace(',', '.').replace(/\s/g, '')) * 100);
    if (!Number.isFinite(minor)) return;
    const delta = minor - acc.balance.amount;
    if (alignMode === 'fact') {
      setBusy(true);
      try {
        await api.checkFact(acc.slug, minor);
        dropCache('home');
        dropCache('entries');
        dropCache('account');
        haptic.success();
        toast({ text: delta === 0 ? 'Факт записан, сходится' : 'Факт записан, остаток выровнен' });
        setAlign(false);
        reload();
      } catch {
        haptic.error();
        toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
      } finally {
        setBusy(false);
      }
      return;
    }
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
          <div className="nums text-[34px] font-bold leading-10 tracking-[-0.02em]">{money(shown, liability ? 'auto' : 'none')}</div>
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

        {kop ? (
          <div className="mt-4">
            <Card>
              <CardHead title={`${kop.percent_bp / 100} % с поступлений`} />
              <div className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="text-[16px]">Перевести в копилку</span>
                <span className="nums text-[17px] font-bold">{money(kop.due, 'none')}</span>
              </div>
              <div className="nums text-[13px] leading-5 text-hint">
                <div>≈ {moneyWhole(kop.due_rub, 'none')} по курсу {kop.rate.source === 'exchange' && kop.rate.op_date ? `обмена ${dateLong(kop.rate.op_date)}` : 'дня'}</div>
                <div>
                  начислено {money(kop.accrued, 'none')}, переведено {money(kop.transferred, 'none')}
                  {kop.surplus.amount > 0 ? `, запас ${money(kop.surplus, 'none')}` : ''}
                </div>
              </div>
              <div className="mt-2 border-t border-inset pt-2">
                {(kop.items ?? []).map((i) => (
                  <button key={i.entry_id} type="button" className="block w-full py-1.5 text-left" onClick={() => openEntry(i.entry_id)}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="nums truncate text-[15px]">
                        {money(i.amount, 'plus')} · {dateLong(i.op_date)}
                      </span>
                      <span className={`nums shrink-0 text-[15px] font-medium ${i.status === 'covered' ? 'text-hint' : ''}`}>
                        {i.status === 'covered' ? 'отложено' : `осталось ${money(i.left, 'none')}`}
                      </span>
                    </div>
                    <div className="nums truncate text-[13px] leading-4 text-hint">
                      10 % = {money(i.accrued, 'none')}
                      {i.accrued.currency !== i.accrued_aed.currency ? ` ≈ ${money(i.accrued_aed, 'none')}` : ''}
                      {i.status === 'partial' ? `, отложено ${money(i.covered, 'none')}` : ''}
                      {i.description ? ` · ${i.description}` : ''}
                    </div>
                  </button>
                ))}
              </div>
            </Card>
          </div>
        ) : null}

        {check ? (
          <div className="mt-4">
            <Card>
              <CardHead title="Сверка" />
              <div className="flex items-baseline justify-between gap-3 py-1.5">
                <span className="text-[16px]">Должно быть по учёту</span>
                <span className="nums text-[17px] font-bold">{money(check.expected, 'none')}</span>
              </div>
              <div className="nums text-[13px] leading-5 text-hint">
                <div>
                  {money(check.base, 'none')}
                  {check.base_note ? ` — ${check.base_note}` : ''}
                </div>
                {check.items.map((i) => (
                  <button key={i.entry_id} type="button" className="block w-full truncate text-left" onClick={() => openEntry(i.entry_id)}>
                    {money(i.amount, i.amount.amount < 0 ? 'auto' : 'plus')} · {dateLong(i.op_date)} · {i.description}
                  </button>
                ))}
              </div>
              {check.mismatch ? (
                <div className="nums mt-1 text-[13px] leading-4 text-danger">
                  Остаток в учёте {money(check.ledger, 'none')}, расходится на {money(check.mismatch, 'auto')}
                </div>
              ) : null}
              <div className="mt-2 flex items-baseline justify-between gap-3 border-t border-inset py-2">
                <span className="text-[16px]">По факту</span>
                <span className="nums text-[17px] font-bold">
                  {check.fact ? money(check.fact.amount, 'none') : '— пересчитать'}
                </span>
              </div>
              {check.fact ? (
                <div className="nums text-[13px] leading-4 text-hint">
                  пересчитано {dateLong(check.fact.date)}
                  {check.fact.diff.amount !== 0
                    ? `, по учёту было ${money(check.fact.ledger_before, 'none')}, разница ${money(check.fact.diff, check.fact.diff.amount < 0 ? 'auto' : 'plus')}`
                    : ', сошлось'}
                </div>
              ) : null}
              <div className="mt-3">
                <Button
                  kind="secondary"
                  onClick={() => {
                    setAlignMode('fact');
                    setFactText('');
                    setAlign(true);
                  }}
                >
                  Ввести факт
                </Button>
              </div>
            </Card>
          </div>
        ) : null}

        {/* Кнопки в ряд по 50 %: столбик из двух одинаковых серых плашек во всю ширину читался
            как «два варианта одного и того же» и съедал 200 CSS над лентой (M13). Карточка вокруг
            них — третья вложенная поверхность подряд, поэтому её нет. */}
        {/* Тексты полные, как в 4.4: «Выровнять» само по себе не говорит, что выравнивают (Н12). */}
        <div className="mt-4 flex gap-2">
          <span className="min-w-0 flex-1">
            <Button
              kind="secondary"
              onClick={() => {
                setAlignMode('align');
                setAlign(true);
              }}
            >
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
          title={alignMode === 'fact' ? 'Сколько лежит по факту' : 'Выровнять остаток'}
          onClose={() => setAlign(false)}
          footer={
            <Button onClick={submitAlign} loading={busy}>
              {alignMode === 'fact' ? 'Записать факт' : 'Выровнять'}
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
