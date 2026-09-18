import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../lib/api';
import { useResource } from '../app/data';
import { dateLong, humanizeDates, money, moneyWhole, monthPrep } from '../lib/format';
import { Button, Card, CardHead, Empty, GroupTitle, LinkAction, LoadError, Row, Screen, Segment } from '../components/ui';
import { AccountRow, EntryRow } from '../components/rows';
import { CategoryChip, ShareBar } from '../components/Charts';
import { HomeSkeleton } from '../components/Skeleton';
import { goMoreSub, goTab, openAccount, openEntry } from '../app/router';
import type { HomeResponse, ViewCurrency } from '../lib/types';

const VIEWS: { value: ViewCurrency; label: string }[] = [
  { value: 'RUB', label: '₽' },
  { value: 'USD', label: '$' },
  { value: 'AED', label: 'AED' },
];

export function Home() {
  const [view, setView] = useState<ViewCurrency>('RUB');
  const { data, error, loading, reload, set } = useResource<HomeResponse>('home', () => api.home('RUB'));

  if (loading) return <HomeSkeleton />;
  if (error || !data) {
    return (
      <Screen>
        <LoadError onRetry={reload} />
      </Screen>
    );
  }

  const total = data.totals_by_view.net_worth[view];
  const frozen = data.frozen_rub.amount > 0;
  const family = data.family;

  const toggleFamily = () => {
    const next = { ...data, family: { ...family, visible: !family.visible } };
    set(next);
    void api.putSettings({ family_block_visible: !family.visible });
  };

  return (
    <Screen>
      <div className="pt-5">
        <div className="text-[13px] leading-4 text-hint">Мои деньги</div>
        <div
          className={`nums mt-1 font-bold tracking-[-0.02em] ${
            moneyWhole(total, 'none').length > 12 ? 'text-[32px] leading-9' : 'text-[40px] leading-[44px]'
          }`}
        >
          {moneyWhole(total, 'none')}
        </div>
        <div className="mt-3">
          <Segment options={VIEWS} value={view} onChange={setView} />
        </div>
        {frozen ? (
          <div className="nums mt-3 text-[15px] leading-5 text-hint">
            свободно в рублях {moneyWhole(data.free_rub, 'none')}
          </div>
        ) : null}
      </div>

      {data.groups.map((g) => (
        <section key={g.key}>
          <GroupTitle title={g.title} right={moneyWhole(data.totals_by_view.groups[g.key][view], 'none')} />
          <Card>
            {g.accounts.map((a) => (
              <AccountRow key={a.id} a={a} onClick={openAccount} />
            ))}
          </Card>
        </section>
      ))}

      <section className="mt-6">
        <Card>
          <button type="button" className="flex w-full items-center justify-between" onClick={toggleFamily}>
            <span className="text-[17px] font-semibold">Семейные</span>
            {family.visible ? (
              <ChevronUp size={20} className="text-hint" />
            ) : (
              <ChevronDown size={20} className="text-hint" />
            )}
          </button>
          {family.visible ? (
            <div className="mt-2">
              {family.accounts.map((a) => (
                <AccountRow key={a.id} a={a} onClick={openAccount} />
              ))}
              {family.debt.amount !== 0 ? (
                <>
                  <Row
                    indent
                    wrap
                    title={family.direction === 'i_owe' ? 'Долг семье' : 'Семья должна вам'}
                    subtitle={
                      family.frozen_note
                        ? `заморожено ${moneyWhole(family.frozen_rub, 'none')} ${humanizeDates(family.frozen_note)}`
                        : undefined
                    }
                    right={money({ ...family.debt, amount: Math.abs(family.debt.amount) }, 'none')}
                  />
                  {family.today_repay_rub ? (
                    <div className="nums pl-[56px] text-[13px] leading-4 text-hint">
                      На возврат сегодня {moneyWhole(family.today_repay_rub, 'none')}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="py-2 text-[15px] text-hint">Долгов перед семьёй нет</div>
              )}
            </div>
          ) : null}
        </Card>
      </section>

      {data.upcoming.length > 0 ? (
        <section className="mt-3">
          <Card>
            <CardHead title="Ближайшие платежи" action={<LinkAction onClick={() => goMoreSub('calendar')}>Все</LinkAction>} />
            {data.upcoming.slice(0, 3).map((p) => (
              <Row
                key={p.id}
                title={p.title}
                subtitle={
                  <span className={p.overdue ? 'text-danger' : undefined}>{dateLong(p.next_date)}</span>
                }
                right={money(p.amount, 'none')}
              />
            ))}
          </Card>
        </section>
      ) : null}

      <section className="mt-3">
        <Card>
          <CardHead title="Последние" action={<LinkAction onClick={() => goTab('entries')}>Все</LinkAction>} />
          {data.recent.length === 0 ? (
            <Empty text="Операций пока нет" />
          ) : (
            data.recent.slice(0, 5).map((e) => <EntryRow key={e.id} e={e} onClick={openEntry} />)
          )}
        </Card>
      </section>

      <section className="mt-3">
        <Card>
          <CardHead
            title={`Траты в ${monthPrep(data.month.month)}`}
            action={<span className="nums text-[15px] font-medium">{moneyWhole(data.month.expense_total, 'none')}</span>}
          />
          <ShareBar parts={data.month.top_categories} />
          <div className="mt-3 flex flex-wrap gap-2">
            {data.month.top_categories.map((c) => (
              <CategoryChip
                key={c.category_id}
                name={c.name}
                color={c.color}
                icon={c.icon}
                amount={c.amount}
                onClick={() => goTab('analytics')}
              />
            ))}
          </div>
          <div className="mt-4">
            <Button kind="secondary" onClick={() => goTab('analytics')}>
              Вся аналитика
            </Button>
          </div>
        </Card>
      </section>
    </Screen>
  );
}
