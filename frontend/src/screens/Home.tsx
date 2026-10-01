import { useState } from 'react';
import { BarChart3, ChevronDown, ChevronRight, ChevronUp, Eye, EyeOff, List, PiggyBank, Plus, Snowflake } from 'lucide-react';
import { api } from '../lib/api';
import { useResource } from '../app/data';
import { haptic } from '../app/telegram';
import { dateLong, frozenBoth, frozenNote, money, moneyWhole, monthPrep } from '../lib/format';
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
        {data.frozen_rub.amount > 0 || (data.frozen_aed?.amount ?? 0) > 0 ? (
          <div className="nums mt-3 flex items-start gap-1.5 text-[15px] leading-5 text-hint">
            <Snowflake size={16} className="mt-0.5 shrink-0" />
            <span>
              Заморожено под семью: {frozenBoth(data.frozen_rub, data.frozen_aed)}
              {data.frozen_aed && data.frozen_aed.amount > 0 && data.free_aed ? (
                <span className="block">Свободно дирхамов: {moneyWhole(data.free_aed, 'auto')}</span>
              ) : null}
            </span>
          </div>
        ) : null}
        {data.shortfall_rub ? (
          <div className="nums mt-3 text-[15px] font-medium leading-5 text-danger">
            Рублей меньше, чем заморожено под семью, на {moneyWhole(data.shortfall_rub, 'none')}
          </div>
        ) : null}
        {data.shortfall_aed ? (
          <div className="nums mt-1 text-[15px] font-medium leading-5 text-danger">
            Дирхамов меньше, чем заблокировано, на {moneyWhole(data.shortfall_aed, 'none')}
          </div>
        ) : null}
        {/* 01.10 Артём: с каждого поступления 10 % в копилку — «чтобы я знал, сколько туда перевести». */}
        {data.kopilka && data.kopilka.due.amount > 0 ? (
          <button
            type="button"
            className="nums mt-3 flex w-full items-center gap-1.5 text-left text-[15px] font-medium leading-5"
            onClick={() => openAccount(data.kopilka!.account.id)}
          >
            <PiggyBank size={16} className="shrink-0 text-blue" />
            <span>
              В копилку перевести: {moneyWhole(data.kopilka.due, 'none')} (≈ {moneyWhole(data.kopilka.due_rub, 'none')})
            </span>
            <ChevronRight size={16} className="shrink-0 text-hint" />
          </button>
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
            <Snowflake size={14} /> {data.frozen_rub.amount > 0 || (data.frozen_aed?.amount ?? 0) > 0 ? `взаимозачёт ${frozenBoth(data.frozen_rub, data.frozen_aed)}` : 'взаимозачёта нет'}
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

      {/* 29.09 Артём: «должны быть наличные дирхамы мои и родительские» — семейные счета отдельной
          группой карточек. В «Мои деньги» не входят. */}
      {family.accounts.length > 0 ? (
        <section className="mt-6">
          <div className="flex items-baseline justify-between px-1">
            <span className="text-[17px] font-bold">Семейные</span>
            <span className="nums text-[15px] text-hint">
              {moneyWhole({ amount: family.accounts.reduce((s, a) => s + (a.balance.currency === 'AED' ? a.balance.amount : 0), 0), currency: 'AED' }, 'none')}
            </span>
          </div>
          <div className="mt-0.5 px-1 text-[13px] leading-4 text-hint">родительские деньги, в «Мои деньги» не входят</div>
          {family.accounts.map((a) => (
            <AccountCard key={a.id} a={a} onClick={openAccount} />
          ))}
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
              // 28.09: часть взаимозачёта может стоять не рублями, а блоком дирхамов на Машреке.
              const blockAed = family.frozen_aed?.amount ?? 0;
              const offsetAed = family.frozen_rub.amount > 0 ? Math.max(0, Math.abs(family.debt.amount) - blockAed) : 0;
              const total = parts.reduce((s, p) => s + p.aed, 0) + offsetAed + blockAed;
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
                    {blockAed ? <span style={{ width: `${share(blockAed)}%`, background: 'var(--c-frozen)' }} /> : null}
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
                    {blockAed ? (
                      <div className="flex items-start gap-3 py-2.5">
                        <span className="mt-1.5 h-3 w-3 shrink-0 rounded-full" style={{ background: 'var(--c-frozen)' }} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[16px]">Заблокировано на Машреке</span>
                          <span className="block text-[13px] leading-4 text-hint">вместо потраченных рублей</span>
                        </span>
                        <span className="nums text-[16px] font-semibold">{money({ amount: blockAed, currency: 'AED' }, 'none')}</span>
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
