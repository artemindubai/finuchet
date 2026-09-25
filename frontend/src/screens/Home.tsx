import { useState } from 'react';
import { BarChart3, ChevronDown, ChevronUp, Eye, EyeOff, List, Plus, Snowflake } from 'lucide-react';
import { api } from '../lib/api';
import { useResource } from '../app/data';
import { haptic } from '../app/telegram';
import { dateLong, frozenNote, money, moneyWhole, monthPrep } from '../lib/format';
import { Card, CardHead, Empty, LinkAction, LoadError, Row, Screen, Segment } from '../components/ui';
import { AccountCard, EntryRow } from '../components/rows';
import { ShareBar } from '../components/Charts';
import { HomeSkeleton } from '../components/Skeleton';
import { goMoreSub, goTab, openAccount, openEntry } from '../app/router';
import type { AccountView, HomeResponse, ViewCurrency } from '../lib/types';

const VIEWS: { value: ViewCurrency; label: string }[] = [
  { value: 'RUB', label: '₽' },
  { value: 'USD', label: '$' },
  { value: 'AED', label: 'AED' },
];

/** Пустые счета на главной не показываем (25.09: нули удешевляют экран), кроме кредитки с долгом. */
function isEmpty(a: AccountView) {
  const shown = a.role === 'liability' ? a.natural : a.balance;
  return shown.amount === 0 && !a.frozen;
}

function QuickAction({ icon, label, onClick }: { icon: JSX.Element; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="flex flex-col items-center gap-2 text-center"
      onClick={() => {
        haptic.tap();
        onClick();
      }}
    >
      <span className="card-lift flex h-[56px] w-[56px] items-center justify-center rounded-[18px] bg-card text-blue">{icon}</span>
      <span className="text-[13px] font-medium leading-4">{label}</span>
    </button>
  );
}

export function Home({ onAdd }: { onAdd?: () => void }) {
  const [view, setView] = useState<ViewCurrency>('RUB');
  const [showEmpty, setShowEmpty] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const { data, error, loading, reload, set } = useResource<HomeResponse>('home', () => api.home('RUB'));

  if (loading) return <HomeSkeleton />;
  if (error || !data) {
    return (
      <Screen>
        <LoadError onRetry={reload} />
      </Screen>
    );
  }

  const base = data.totals_by_view.my_money?.[view] ?? data.totals_by_view.net_worth[view];
  const hiddenTotal = data.hidden?.total?.[view];
  // Кнопка «Копилка»: открыта — копилка входит в итог, закрыта — нет (25.09, Артём).
  const my = showHidden && hiddenTotal ? { ...base, amount: base.amount + hiddenTotal.amount } : base;
  const family = data.family;
  const accounts = data.groups.flatMap((g) => g.accounts);
  const visible = accounts.filter((a) => showEmpty || !isEmpty(a));
  const emptyCount = accounts.filter(isEmpty).length;
  const hidden = data.hidden?.accounts ?? [];

  const toggleFamily = () => {
    const next = { ...data, family: { ...family, visible: !family.visible } };
    set(next);
    void api.putSettings({ family_block_visible: !family.visible });
  };

  return (
    <Screen>
      <div className="pt-6">
        <div className="text-[15px] font-medium leading-5 text-hint">{showHidden ? 'Мои деньги с копилкой' : 'Мои деньги'}</div>
        <div
          className={`nums mt-1 font-extrabold tracking-[-0.03em] ${
            moneyWhole(my, 'none').length > 12 ? 'text-[36px] leading-10' : 'text-[44px] leading-[48px]'
          }`}
        >
          {moneyWhole(my, 'none')}
        </div>
        <div className="mt-3">
          <Segment options={VIEWS} value={view} onChange={setView} />
        </div>
        {data.shortfall_rub ? (
          <div className="nums mt-3 text-[15px] font-medium leading-5 text-danger">
            Рублей меньше, чем заморожено под семью, на {moneyWhole(data.shortfall_rub, 'none')}
          </div>
        ) : null}
      </div>

      {/* Две плитки сверху, как у Т-Банка: траты месяца и семейный взаимозачёт. */}
      <div className="mt-5 grid grid-cols-2 gap-3">
        <button
          type="button"
          className="card-lift flex min-h-[132px] flex-col rounded-[24px] bg-card p-4 text-left"
          onClick={() => goTab('analytics')}
        >
          <span className="text-[17px] font-bold leading-[22px]">Все операции</span>
          <span className="mt-1 text-[15px] leading-5 text-hint">Трат в {monthPrep(data.month.month)}</span>
          <span className="nums mt-0.5 text-[17px] font-semibold">{moneyWhole(data.month.expense_total, 'none')}</span>
          <span className="mt-auto pt-3">
            <ShareBar parts={data.month.top_categories} />
          </span>
        </button>
        <button
          type="button"
          className="card-lift flex min-h-[132px] flex-col rounded-[24px] bg-card p-4 text-left"
          onClick={() => {
            if (!family.visible) toggleFamily();
            setTimeout(() => document.getElementById('family')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
          }}
        >
          <span className="text-[17px] font-bold leading-[22px]">Семейные</span>
          <span className="nums mt-1 text-[17px] font-semibold">{moneyWhole(family.total, 'none')}</span>
          <span className="mt-auto flex items-center gap-1.5 pt-3 text-[13px] leading-4 text-hint">
            <Snowflake size={14} /> {data.frozen_rub.amount > 0 ? `взаимозачёт ${moneyWhole(data.frozen_rub, 'none')}` : 'взаимозачёта нет'}
          </span>
        </button>
      </div>

      <div className="mt-5 grid grid-cols-4 gap-2">
        <QuickAction icon={<Plus size={24} />} label="Добавить" onClick={() => (onAdd ? onAdd() : goTab('entries'))} />
        <QuickAction icon={<List size={24} />} label="Операции" onClick={() => goTab('entries')} />
        <QuickAction icon={<BarChart3 size={24} />} label="Аналитика" onClick={() => goTab('analytics')} />
        <QuickAction
          icon={showHidden ? <EyeOff size={24} /> : <Eye size={24} />}
          label="Копилка"
          onClick={() => setShowHidden((v) => !v)}
        />
      </div>

      <section className="mt-3">
        {visible.map((a) => (
          <AccountCard key={a.id} a={a} onClick={openAccount} />
        ))}
        {emptyCount > 0 ? (
          <div className="mt-3 text-center">
            <LinkAction onClick={() => setShowEmpty((v) => !v)}>
              {showEmpty ? 'Скрыть пустые счета' : `Показать пустые счета (${emptyCount})`}
            </LinkAction>
          </div>
        ) : null}
      </section>

      {hidden.length > 0 && showHidden ? (
        <section className="mt-4">
          <div className="mb-1 flex items-baseline justify-between px-1">
            <span className="text-[17px] font-bold">Копилка</span>
            <span className="nums text-[15px] text-hint">{moneyWhole(data.hidden.total[view], 'none')}</span>
          </div>
          {hidden.map((a) => (
            <AccountCard key={a.id} a={a} onClick={openAccount} />
          ))}
          <div className="mt-2 px-1 text-[13px] leading-4 text-hint">Пока копилка открыта, она входит в итог. Закроешь — снова спрячется</div>
        </section>
      ) : null}

      {family.visible ? (
        <section className="mt-6" id="family">
          <Card className="card-lift rounded-[24px] p-5">
            <button type="button" className="flex w-full items-center justify-between" onClick={toggleFamily}>
              <span className="text-[19px] font-bold">Семейные деньги</span>
              <ChevronUp size={20} className="text-hint" />
            </button>
            {(() => {
              // 25.09 Артём: «зайти внутрь семейных и видеть, где они лежат на самом деле» —
              // карта, наличные, взаимозачёт (рубли на Т-Банке под взятые дирхамы). Всё в AED.
              const parts = family.accounts.map((a) => ({ key: String(a.id), name: a.name, aed: a.balance.currency === 'AED' ? a.balance.amount : 0, a }));
              const offsetAed = family.frozen_rub.amount > 0 ? Math.abs(family.debt.amount) : 0;
              const total = parts.reduce((s, p) => s + p.aed, 0) + offsetAed;
              const colors = ['#FF6A13', '#8E939A', '#2E6AE6'];
              const share = (v: number) => (total ? Math.max(2, Math.round((v / total) * 100)) : 0);
              return (
                <>
                  <div className="nums mt-2 text-[28px] font-extrabold leading-8">{money({ amount: total, currency: 'AED' }, 'none')}</div>
                  <div className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-inset">
                    {parts.map((p, i) => (
                      <span key={p.key} style={{ width: `${share(p.aed)}%`, background: colors[i % 3] }} />
                    ))}
                    {offsetAed ? <span style={{ width: `${share(offsetAed)}%`, background: colors[2] }} /> : null}
                  </div>
                  <div className="mt-3">
                    {parts.map((p, i) => (
                      <button
                        key={p.key}
                        type="button"
                        className="flex w-full items-center gap-3 py-2.5 text-left"
                        onClick={() => openAccount(p.a.id)}
                      >
                        <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: colors[i % 3] }} />
                        <span className="min-w-0 flex-1 truncate text-[16px]">{p.name}</span>
                        <span className="nums text-[16px] font-semibold">{money({ amount: p.aed, currency: 'AED' }, 'none')}</span>
                      </button>
                    ))}
                    {offsetAed ? (
                      <div className="flex items-start gap-3 py-2.5">
                        <span className="mt-1.5 h-3 w-3 shrink-0 rounded-full" style={{ background: colors[2] }} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[16px]">Взаимозачёт, рубли на Т-Банке</span>
                          <span className="nums block text-[13px] leading-4 text-hint">
                            {frozenNote(family.frozen_rub, family.frozen_note)}
                          </span>
                        </span>
                        <span className="nums text-[16px] font-semibold">{money({ amount: offsetAed, currency: 'AED' }, 'none')}</span>
                      </div>
                    ) : null}
                  </div>
                </>
              );
            })()}
          </Card>
        </section>
      ) : (
        <button type="button" className="mt-6 flex w-full items-center justify-between px-1" onClick={toggleFamily}>
          <span className="text-[17px] font-bold">Семейные деньги</span>
          <ChevronDown size={20} className="text-hint" />
        </button>
      )}

      {data.upcoming.length > 0 ? (
        <section className="mt-3">
          <Card className="card-lift rounded-[24px] p-5">
            <CardHead title="Ближайшие платежи" action={<LinkAction onClick={() => goMoreSub('calendar')}>Все</LinkAction>} />
            {data.upcoming.slice(0, 3).map((p) => (
              <Row
                key={p.id}
                title={p.title}
                subtitle={<span className={p.overdue ? 'text-danger' : undefined}>{dateLong(p.next_date)}</span>}
                right={money(p.amount, 'none')}
              />
            ))}
          </Card>
        </section>
      ) : null}

      <section className="mt-3">
        <Card className="card-lift rounded-[24px] p-5">
          <CardHead title="Последние" action={<LinkAction onClick={() => goTab('entries')}>Все</LinkAction>} />
          {data.recent.length === 0 ? (
            <Empty text="Операций пока нет" />
          ) : (
            data.recent.slice(0, 5).map((e) => <EntryRow key={e.id} e={e} onClick={openEntry} />)
          )}
        </Card>
      </section>
    </Screen>
  );
}
