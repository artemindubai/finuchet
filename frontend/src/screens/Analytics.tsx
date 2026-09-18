import { useState } from 'react';
import { BarChart3, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, PieChart } from 'lucide-react';
import { api } from '../lib/api';
import { useResource } from '../app/data';
import { bp, moneyWhole, monthLong, monthPrep } from '../lib/format';
import { Card, CardHead, Empty, LoadError, ProgressBar, Row, Screen, Segment } from '../components/ui';
import { CircleIcon, dataColor } from '../components/Icon';
import { Donut, DonutChips, MonthBars } from '../components/Charts';
import { AnalyticsSkeleton } from '../components/Skeleton';
import { Sheet } from '../components/Sheet';
import { EntryRow } from '../components/rows';
import { openEntry } from '../app/router';
import { haptic } from '../app/telegram';
import { currentMonth } from '../lib/today';
import type { AnalyticsResponse, Breakdown, EntryShort, Money } from '../lib/types';

const MODES = [
  { value: 'expense' as const, label: 'Расходы' },
  { value: 'income' as const, label: 'Доходы' },
];

export function Analytics() {
  const [month, setMonth] = useState(currentMonth());
  const [mode, setMode] = useState<'expense' | 'income'>('expense');
  const [chart, setChart] = useState<'donut' | 'bars'>('donut');
  const [openSource, setOpenSource] = useState<number | null>(null);
  const [drill, setDrill] = useState<{ id: number; name: string } | null>(null);

  const { data, error, loading, reload } = useResource<AnalyticsResponse>(
    `analytics:${month}`,
    () => api.analytics(month),
  );

  if (loading) return <AnalyticsSkeleton />;
  if (error || !data) {
    return (
      <Screen>
        <LoadError onRetry={reload} />
      </Screen>
    );
  }

  const isExpense = mode === 'expense';
  const total: Money = isExpense ? data.expense_total : data.income_total;
  const rows: Breakdown[] = isExpense
    ? data.categories.map((c) => ({
        category_id: c.category_id, name: c.name, color: c.color, amount: c.amount,
        share_bp: c.share_bp, icon: c.icon,
      }))
    : data.income_sources.map((s) => ({
        source_id: s.source_id, name: s.name, color: s.color, amount: s.amount,
        share_bp: s.share_bp, icon: s.icon,
      }));

  return (
    <>
      <Screen>
        <div className="flex h-[52px] items-center justify-center gap-2">
          <button
            type="button"
            aria-label="Предыдущий месяц"
            className="flex h-11 w-11 items-center justify-center"
            disabled={!data.prev_month}
            onClick={() => {
              haptic.select();
              if (data.prev_month) setMonth(data.prev_month);
            }}
          >
            <ChevronLeft size={22} className={data.prev_month ? '' : 'text-hint opacity-40'} />
          </button>
          <span className="min-w-[150px] text-center text-[17px] font-semibold">{monthLong(month)}</span>
          <button
            type="button"
            aria-label="Следующий месяц"
            className="flex h-11 w-11 items-center justify-center"
            disabled={!data.next_month}
            onClick={() => {
              haptic.select();
              if (data.next_month) setMonth(data.next_month);
            }}
          >
            <ChevronRight size={22} className={data.next_month ? '' : 'text-hint opacity-40'} />
          </button>
        </div>

        <div className="mb-4 mt-1">
          <Segment options={MODES} value={mode} onChange={setMode} />
        </div>

        <div className="flex items-end justify-between">
          <div>
            <div className="nums text-[32px] font-bold leading-9 tracking-[-0.02em]">{moneyWhole(total, 'none')}</div>
            <div className="mt-0.5 text-[13px] text-hint">
              {isExpense ? 'Траты' : 'Доходы'} в {monthPrep(month)}
            </div>
          </div>
          <div className="pb-0.5">
            <Segment
              options={[
                { value: 'donut' as const, label: 'Кольцо', icon: <PieChart size={20} strokeWidth={1.8} /> },
                { value: 'bars' as const, label: 'Столбики', icon: <BarChart3 size={20} strokeWidth={1.8} /> },
              ]}
              value={chart}
              onChange={setChart}
            />
          </div>
        </div>

        {total.amount === 0 ? (
          <div className="mt-6">
            <Card>
              <Empty text={isExpense ? 'В этом месяце трат не было' : 'В этом месяце доходов не было'} />
            </Card>
          </div>
        ) : chart === 'donut' ? (
          <div className="mt-4">
            <Card>
              <Donut
                rows={rows}
                onPick={(id) => setDrill({ id, name: rows.find((r) => r.category_id === id)?.name ?? '' })}
              />
              <div className="mt-3">
                <DonutChips
                  rows={rows}
                  onPick={(id) => setDrill({ id, name: rows.find((r) => r.category_id === id)?.name ?? '' })}
                />
              </div>
            </Card>
          </div>
        ) : (
          <div className="mt-4">
            <Card>
              <MonthBars data={data.by_month} selected={month} onSelect={setMonth} />
            </Card>
          </div>
        )}

        <div className="mt-3">
          <Card>
            {rows.map((r) => (
              <Row
                key={r.category_id ?? r.source_id}
                left={<CircleIcon name={iconOf(data, r)} color={dataColor(r.color)} />}
                title={r.name}
                right={moneyWhole(r.amount, 'none')}
                rightSub={bp(r.share_bp)}
                onClick={
                  r.category_id
                    ? () => setDrill({ id: r.category_id!, name: r.name })
                    : undefined
                }
              />
            ))}
          </Card>
        </div>

        <div className="mt-3">
          <Card>
            <CardHead title="Доходы и расходы по месяцам" />
            <MonthBars data={data.by_month} selected={month} onSelect={setMonth} />
          </Card>
        </div>

        <div className="mt-3">
          <Card>
            <CardHead title="Откуда деньги" />
            {data.income_sources.map((s) => (
              <div key={s.source_id}>
                <button
                  type="button"
                  className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 py-2 text-left active:bg-inset"
                  onClick={() => {
                    haptic.tap();
                    setOpenSource(openSource === s.source_id ? null : s.source_id);
                  }}
                >
                  <CircleIcon name={s.icon} color={dataColor(s.color)} />
                  <span className="min-w-0 flex-1 truncate text-[16px] font-medium leading-5">{s.name}</span>
                  <span className="nums shrink-0 text-[16px] font-medium">{moneyWhole(s.amount, 'none')}</span>
                  {s.projects.length > 0 ? (
                    openSource === s.source_id ? (
                      <ChevronUp size={18} className="shrink-0 text-hint" />
                    ) : (
                      <ChevronDown size={18} className="shrink-0 text-hint" />
                    )
                  ) : null}
                </button>
                {openSource === s.source_id && s.projects.length > 0 ? (
                  <div className="mb-1 ml-[52px]">
                    {s.projects.map((p) => (
                      <div key={p.project} className="flex items-baseline justify-between py-1.5">
                        <span className="truncate text-[15px]">{p.project}</span>
                        <span className="nums text-[15px]">{moneyWhole(p.amount, 'none')}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </Card>
        </div>

        {data.limits.length > 0 ? (
          <div className="mt-3">
            <Card>
              <CardHead title="Лимиты" />
              {data.limits.map((l) => {
                const over = l.spent.amount > l.limit.amount;
                return (
                  <div key={l.category_id} className="py-2">
                    <div className="flex items-baseline justify-between">
                      <span className="text-[16px] font-medium">{l.name}</span>
                      <span className={`nums text-[15px] ${over ? 'text-danger' : 'text-hint'}`}>
                        {moneyWhole(l.spent, 'none')} из {moneyWhole(l.limit, 'none')}
                      </span>
                    </div>
                    <div className="mt-2">
                      <ProgressBar
                        value={l.spent.amount}
                        max={l.limit.amount}
                        danger={over}
                        color={dataColor(data.categories.find((c) => c.category_id === l.category_id)?.color)}
                      />
                    </div>
                  </div>
                );
              })}
            </Card>
          </div>
        ) : null}
      </Screen>

      {drill ? <CategorySheet id={drill.id} name={drill.name} month={month} onClose={() => setDrill(null)} /> : null}
    </>
  );
}

function iconOf(data: AnalyticsResponse, r: Breakdown): string {
  if (r.category_id) return data.categories.find((c) => c.category_id === r.category_id)?.icon ?? 'dots';
  return data.income_sources.find((s) => s.source_id === r.source_id)?.icon ?? 'dots';
}

function CategorySheet({
  id,
  name,
  month,
  onClose,
}: {
  id: number;
  name: string;
  month: string;
  onClose: () => void;
}) {
  const { data, loading } = useResource<{ items: EntryShort[]; total: Money }>(
    `cat:${id}:${month}`,
    () => api.categoryEntries(id, month),
  );
  return (
    <Sheet title={name} onClose={onClose}>
      {loading || !data ? (
        <div className="py-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 py-3">
              <span className="skeleton h-10 w-10 rounded-full" />
              <span className="skeleton h-4 flex-1" />
            </div>
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <Empty text="Операций пока нет" />
      ) : (
        <>
          <div className="nums pb-2 text-[13px] text-hint">
            {monthLong(month)} · {moneyWhole(data.total, 'none')}
          </div>
          {data.items.map((e) => (
            <EntryRow
              key={e.id}
              e={e}
              onClick={(entryId) => {
                onClose();
                openEntry(entryId);
              }}
            />
          ))}
        </>
      )}
    </Sheet>
  );
}
