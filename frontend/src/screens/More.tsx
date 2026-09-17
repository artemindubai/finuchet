import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache, useResource } from '../app/data';
import {
  dateLong, money, monthLong, num, plural, rate, rateSource, REPEAT_LABEL, timeDubai,
} from '../lib/format';
import { Button, Card, CardHead, Empty, LoadError, MenuRow, ProgressBar, Row, Screen, Segment } from '../components/ui';
import { accountColor, CircleIcon } from '../components/Icon';
import { TrancheRow } from '../components/rows';
import { Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { haptic } from '../app/telegram';
import { openEntry } from '../app/router';
import { currentMonth, plusMonths, recentMonths, today } from '../lib/today';
import type {
  DebtsResponse, Goal, LimitRow, PlannedItem, RatesResponse, Refs, SettingsResponse,
} from '../lib/types';

type Sub =
  | null
  | 'debts'
  | 'calendar'
  | 'goals'
  | 'limits'
  | 'accounts'
  | 'categories'
  | 'sources'
  | 'opening'
  | 'export'
  | 'settings'
  | 'rates';

export function More({ sub, setSub }: { sub: Sub; setSub: (s: Sub) => void }) {
  const refs = useResource<Refs>('refs', () => api.refs());
  const debts = useResource<DebtsResponse>('debts', () => api.debts());
  const calendar = useResource<{ items: PlannedItem[] }>('calendar', () => api.calendar(today(), plusMonths(today(), 3)));
  const goals = useResource<{ items: Goal[] }>('goals', () => api.goals());
  const limits = useResource<{ items: LimitRow[] }>(`limits:${currentMonth()}`, () => api.limits(currentMonth()));

  if (sub) return <SubScreen sub={sub} onBack={() => setSub(null)} />;

  const moneyAccounts = refs.data?.accounts.filter((a) => a.is_money) ?? [];
  const debtSummary = debts.data
    ? [
        debts.data.family.debt.amount !== 0 ? money(debts.data.family.debt, 'none') : null,
        debts.data.tax.amount.amount !== 0 ? money(debts.data.tax.amount, 'none') : null,
      ].filter(Boolean).join(', ')
    : '';

  return (
    <Screen>
      <h1 className="py-4 text-[22px] font-bold leading-7 tracking-[-0.01em]">Ещё</h1>

      <Card>
        <MenuRow title="Долги" value={debtSummary || 'нет'} onClick={() => setSub('debts')} />
        <MenuRow
          title="Календарь платежей"
          value={
            calendar.data
              ? `${calendar.data.items.length} ${plural(calendar.data.items.length, 'ближайший', 'ближайших', 'ближайших')}`
              : ''
          }
          onClick={() => setSub('calendar')}
        />
        <MenuRow title="Цели" value={goals.data ? String(goals.data.items.length) : ''} onClick={() => setSub('goals')} />
        <MenuRow
          title="Лимиты"
          value={limits.data ? (limits.data.items.length ? String(limits.data.items.length) : 'не заданы') : ''}
          onClick={() => setSub('limits')}
        />
      </Card>

      <div className="mt-3">
        <Card>
          <MenuRow title="Счета" value={String(moneyAccounts.length)} onClick={() => setSub('accounts')} />
          <MenuRow
            title="Категории"
            value={String(refs.data?.categories.length ?? '')}
            onClick={() => setSub('categories')}
          />
          <MenuRow
            title="Источники дохода"
            value={String(refs.data?.income_sources.length ?? '')}
            onClick={() => setSub('sources')}
          />
        </Card>
      </div>

      <div className="mt-3">
        <Card>
          <MenuRow title="Начальные остатки" onClick={() => setSub('opening')} />
          <MenuRow title="Выгрузка в таблицу" onClick={() => setSub('export')} />
          <MenuRow title="Настройки" onClick={() => setSub('settings')} />
        </Card>
      </div>
    </Screen>
  );
}

const TITLES: Record<NonNullable<Sub>, string> = {
  debts: 'Долги',
  calendar: 'Календарь платежей',
  goals: 'Цели',
  limits: 'Лимиты',
  accounts: 'Счета',
  categories: 'Категории',
  sources: 'Источники дохода',
  opening: 'Начальные остатки',
  export: 'Выгрузка',
  settings: 'Настройки',
  rates: 'Курсы',
};

function SubScreen({ sub, onBack }: { sub: NonNullable<Sub>; onBack: () => void }) {
  return (
    <Screen>
      <div className="sticky top-0 z-20 -mx-4 mb-1 flex h-[52px] items-center bg-bg px-4">
        <button
          type="button"
          aria-label="Назад"
          className="flex h-11 w-11 items-center justify-center"
          onClick={() => {
            haptic.tap();
            onBack();
          }}
        >
          <ChevronLeft size={24} />
        </button>
        <div className="flex-1 truncate text-center text-[17px] font-semibold">{TITLES[sub]}</div>
        <div className="w-11" />
      </div>
      {sub === 'debts' ? <Debts /> : null}
      {sub === 'calendar' ? <Calendar /> : null}
      {sub === 'goals' ? <Goals /> : null}
      {sub === 'limits' ? <Limits /> : null}
      {sub === 'accounts' ? <RefList kind="accounts" /> : null}
      {sub === 'categories' ? <RefList kind="categories" /> : null}
      {sub === 'sources' ? <RefList kind="sources" /> : null}
      {sub === 'opening' ? <Opening /> : null}
      {sub === 'export' ? <Export /> : null}
      {sub === 'settings' ? <Settings /> : null}
      {sub === 'rates' ? <Rates /> : null}
    </Screen>
  );
}

function Debts() {
  const [side, setSide] = useState<'i_owe' | 'owed'>('i_owe');
  const { data, error, loading, reload } = useResource<DebtsResponse>('debts', () => api.debts());
  if (loading) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;
  if (error || !data) return <LoadError onRetry={reload} />;

  const list = side === 'i_owe' ? data.i_owe : data.owed_to_me;
  const nothing = list.length === 0 && (side === 'owed' || (data.tax.amount.amount === 0 && data.family.debt.amount === 0));

  return (
    <>
      <div className="mb-3">
        <Segment
          full
          options={[
            { value: 'i_owe' as const, label: 'Я должен' },
            { value: 'owed' as const, label: 'Мне должны' },
          ]}
          value={side}
          onChange={setSide}
        />
      </div>
      {nothing ? (
        <Card>
          <Empty text="Долгов нет" />
        </Card>
      ) : (
        <Card>
          {list.map((d) => (
            <Row
              key={d.counterparty_id}
              title={d.name}
              subtitle={d.due_date ? `до ${dateLong(d.due_date)}` : undefined}
              right={money(d.amounts[0], 'none')}
              rightSub={d.amounts[0].currency !== 'RUB' ? money(d.in_view, 'none') : undefined}
              onClick={d.entry_ids.length ? () => openEntry(d.entry_ids[0]) : undefined}
            />
          ))}
          {side === 'i_owe' ? (
            <>
              <Row
                title={data.tax.name}
                subtitle={data.tax.due_date ? `до ${dateLong(data.tax.due_date)}` : undefined}
                right={money(data.tax.amount, 'none')}
              />
              <Row
                title={data.credit_card.name}
                right={money(data.credit_card.amount, 'none')}
              />
              {data.family.debt.amount !== 0 ? (
                <Row
                  title={data.family.direction === 'i_owe' ? 'Долг семье' : 'Семья должна вам'}
                  subtitle={`заморожено ${money(data.family.frozen_rub, 'none')}`}
                  right={money({ ...data.family.debt, amount: Math.abs(data.family.debt.amount) }, 'none')}
                />
              ) : null}
            </>
          ) : null}
        </Card>
      )}

      {side === 'i_owe' && data.family.tranches.length > 0 ? (
        <div className="mt-3">
          <Card>
            <CardHead title="Заморозка" />
            {data.family.tranches.map((t) => (
              <TrancheRow key={t.id} t={t} onClick={openEntry} />
            ))}
            {data.family.today_repay_rub ? (
              <div className="nums pt-2 text-[13px] text-hint">
                по курсу сегодня на возврат нужно {money(data.family.today_repay_rub, 'none')}
              </div>
            ) : null}
          </Card>
        </div>
      ) : null}
    </>
  );
}

function Calendar() {
  const { data, error, loading, reload, set } = useResource<{ items: PlannedItem[] }>(
    'calendar',
    () => api.calendar(today(), plusMonths(today(), 3)),
  );
  const [busy, setBusy] = useState<number | null>(null);
  const toast = useToast();
  if (loading) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;
  if (error || !data) return <LoadError onRetry={reload} />;
  if (data.items.length === 0) {
    return (
      <Card>
        <Empty text="Платежей не запланировано" />
      </Card>
    );
  }

  const pay = async (p: PlannedItem) => {
    setBusy(p.id);
    try {
      await api.markPaid(p.id, { op_date: today() });
      set({
        items: data.items.map((x) =>
          x.id === p.id ? { ...x, last_paid: { entry_id: 0, op_date: today() } } : x,
        ),
      });
      dropCache('home');
      dropCache('entries');
      haptic.success();
      toast({ text: 'Записано' });
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card>
      {data.items.map((p) => (
        <div key={p.id} className="flex items-center gap-3 py-2.5">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[16px] font-medium leading-5">{p.title}</div>
            <div className={`mt-0.5 truncate text-[13px] leading-4 ${p.overdue ? 'text-danger' : 'text-hint'}`}>
              {dateLong(p.next_date)} · {REPEAT_LABEL[p.repeat] ?? p.repeat}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className="nums text-[16px] font-medium leading-5">{money(p.amount, 'none')}</div>
            <button
              type="button"
              disabled={busy === p.id}
              className="mt-0.5 text-[13px] font-medium leading-4 text-blue"
              onClick={() => void pay(p)}
            >
              {busy === p.id ? 'Записываю' : 'Оплачено'}
            </button>
          </div>
        </div>
      ))}
    </Card>
  );
}

function Goals() {
  const { data, error, loading, reload } = useResource<{ items: Goal[] }>('goals', () => api.goals());
  if (loading) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;
  if (error || !data) return <LoadError onRetry={reload} />;
  if (data.items.length === 0) {
    return (
      <Card>
        <Empty text="Целей нет" />
      </Card>
    );
  }
  return (
    <Card>
      {data.items.map((g) => (
        <div key={g.id} className="py-2">
          <div className="flex items-baseline justify-between">
            <span className="text-[16px] font-medium">{g.name}</span>
            <span className="nums text-[15px] text-hint">
              {money(g.saved, 'none')} из {money(g.target, 'none')}
            </span>
          </div>
          <div className="mt-2">
            <ProgressBar value={g.saved.amount} max={g.target.amount} />
          </div>
          {g.due_date ? <div className="mt-1.5 text-[13px] text-hint">до {dateLong(g.due_date)}</div> : null}
        </div>
      ))}
    </Card>
  );
}

function Limits() {
  const { data, error, loading, reload, set } = useResource<{ items: LimitRow[] }>(
    `limits:${currentMonth()}`,
    () => api.limits(currentMonth()),
  );
  const [edit, setEdit] = useState<LimitRow | null>(null);
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  if (loading) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;
  if (error || !data) return <LoadError onRetry={reload} />;
  if (data.items.length === 0) {
    return (
      <Card>
        <Empty text="Лимиты не заданы" />
      </Card>
    );
  }

  const save = async () => {
    if (!edit) return;
    const minor = Math.round(Number(value.replace(',', '.').replace(/\s/g, '')) * 100);
    if (!minor) return;
    setBusy(true);
    try {
      const res = await api.putLimit(edit.category_id, { amount: minor, currency: edit.limit.currency, active: true });
      set(res);
      haptic.success();
      toast({ text: 'Лимит сохранён' });
      setEdit(null);
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Card>
        {data.items.map((l) => {
          const over = l.spent.amount > l.limit.amount;
          return (
            <button
              key={l.category_id}
              type="button"
              className="-mx-2 w-[calc(100%+16px)] rounded-inset px-2 py-2 text-left active:bg-inset"
              onClick={() => {
                haptic.tap();
                setValue(num(l.limit.amount).replace(/ /g, ''));
                setEdit(l);
              }}
            >
              <div className="flex items-baseline justify-between">
                <span className="text-[16px] font-medium">{l.name}</span>
                <span className={`nums text-[15px] ${over ? 'text-danger' : 'text-hint'}`}>
                  {money(l.spent, 'none')} из {money(l.limit, 'none')}
                </span>
              </div>
              <div className="mt-2">
                <ProgressBar value={l.spent.amount} max={l.limit.amount} danger={over} />
              </div>
            </button>
          );
        })}
      </Card>
      {edit ? (
        <Sheet
          title={edit.name}
          onClose={() => setEdit(null)}
          footer={
            <Button onClick={save} loading={busy}>
              Готово
            </Button>
          }
        >
          <div className="flex h-[60px] items-center gap-2 rounded-inset bg-inset px-4">
            <input
              autoFocus
              inputMode="decimal"
              className="nums w-full text-[28px] font-semibold"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <span className="text-[17px] text-hint">{edit.limit.currency === 'RUB' ? '₽' : edit.limit.currency}</span>
          </div>
          <div className="mt-2 text-[13px] text-hint">На каждый месяц</div>
        </Sheet>
      ) : null}
    </>
  );
}

function RefList({ kind }: { kind: 'accounts' | 'categories' | 'sources' }) {
  const { data, loading } = useResource<Refs>('refs', () => api.refs());
  const toast = useToast();
  if (loading || !data) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;

  const rows =
    kind === 'accounts'
      ? data.accounts
          .filter((a) => a.is_money)
          .map((a) => ({ id: a.id, name: a.name, hint: a.currency ?? '', icon: a.icon, color: accountColor(a.currency, a.icon) }))
      : kind === 'categories'
        ? data.categories.map((c) => ({ id: c.id, name: c.name, hint: '', icon: c.icon, color: c.color }))
        : data.income_sources.map((s) => ({
            id: s.id,
            name: s.name,
            hint: s.tax_rate_bp ? `налог ${s.tax_rate_bp / 100} %` : '',
            icon: s.icon,
            color: s.color,
          }));

  return (
    <>
      <Card>
        {rows.map((r) => (
          <Row
            key={r.id}
            left={<CircleIcon name={r.icon} color={r.color} />}
            title={r.name}
            subtitle={r.hint || undefined}
            chevron
            onClick={() => toast({ text: 'Правка справочников — в следующей версии' })}
          />
        ))}
      </Card>
      <div className="mt-3">
        <Button kind="secondary" onClick={() => toast({ text: 'Правка справочников — в следующей версии' })}>
          Добавить
        </Button>
      </div>
    </>
  );
}

function Opening() {
  const { data, loading } = useResource<Refs>('refs', () => api.refs());
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  if (loading || !data) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;

  const accounts = data.accounts.filter((a) => a.is_money && a.type !== 'liability');
  const date = today();

  const submit = async () => {
    const items = accounts
      .filter((a) => values[a.slug])
      .map((a) => ({
        account: a.slug,
        amount: Math.round(Number(values[a.slug].replace(',', '.').replace(/\s/g, '')) * 100),
        currency: a.currency!,
      }))
      .filter((i) => Number.isFinite(i.amount) && i.amount !== 0);
    if (items.length === 0) {
      toast({ text: 'Введите хотя бы один остаток' });
      return;
    }
    setBusy(true);
    try {
      await api.openingBalances({ op_date: date, items });
      dropCache('home');
      haptic.success();
      toast({ text: 'Остатки записаны' });
      setValues({});
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mb-3 text-[13px] text-hint">на {dateLong(date)}</div>
      <Card>
        {accounts.map((a) => (
          <div key={a.slug} className="flex items-center gap-3 py-2">
            <CircleIcon name={a.icon} color={accountColor(a.currency, a.icon)} ring={a.type === 'asset_family'} />
            <span className="min-w-0 flex-1 truncate text-[16px] font-medium">{a.name}</span>
            <span className="flex h-11 w-[132px] shrink-0 items-center gap-1 rounded-inset bg-inset px-3">
              <input
                inputMode="decimal"
                className="nums w-full text-right text-[16px]"
                placeholder="0"
                value={values[a.slug] ?? ''}
                onChange={(e) => setValues({ ...values, [a.slug]: e.target.value })}
              />
              <span className="text-[13px] text-hint">{a.currency === 'RUB' ? '₽' : a.currency}</span>
            </span>
          </div>
        ))}
      </Card>
      <div className="mt-5">
        <Button onClick={submit} loading={busy}>
          Записать остатки
        </Button>
      </div>
    </>
  );
}

const SHEETS = [
  { key: 'dds', label: 'ДДС' },
  { key: 'osv', label: 'Оборотка' },
  { key: 'balance', label: 'Баланс' },
  { key: 'journal', label: 'Журнал проводок' },
  { key: 'offbalance', label: 'За балансом' },
];

function Export() {
  const [on, setOn] = useState<Record<string, boolean>>(
    Object.fromEntries(SHEETS.map((s) => [s.key, true])),
  );
  const [period, setPeriod] = useState(currentMonth());
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const send = async () => {
    const sheets = SHEETS.filter((s) => on[s.key]).map((s) => s.key);
    if (sheets.length === 0) {
      toast({ text: 'Выберите хотя бы один лист' });
      return;
    }
    setBusy(true);
    try {
      await api.exportXlsx({ period, sheets });
      haptic.success();
      toast({ text: 'Файл отправлен в чат' });
    } catch {
      haptic.error();
      toast({ text: 'Не отправилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Card>
        {SHEETS.map((s) => (
          <button
            key={s.key}
            type="button"
            className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 py-3 text-left active:bg-inset"
            onClick={() => {
              haptic.select();
              setOn({ ...on, [s.key]: !on[s.key] });
            }}
          >
            <span className="flex-1 text-[17px]">{s.label}</span>
            <span
              className="flex h-[30px] w-[50px] items-center rounded-full p-0.5 transition-colors duration-[80ms]"
              style={{ background: on[s.key] ? 'var(--c-blue)' : 'var(--c-inset)' }}
            >
              <span
                className="h-[26px] w-[26px] rounded-full bg-white transition-transform duration-[120ms]"
                style={{ transform: on[s.key] ? 'translateX(20px)' : 'none' }}
              />
            </span>
          </button>
        ))}
      </Card>
      <div className="mt-3">
        <Card>
          <CardHead title="Период" />
          <div className="flex flex-wrap gap-2">
            {recentMonths(3).map((p) => (
              <button
                key={p}
                type="button"
                className={`h-[34px] rounded-full px-[14px] text-[13px] font-medium ${
                  period === p ? 'bg-blue text-white' : 'bg-inset'
                }`}
                onClick={() => {
                  haptic.select();
                  setPeriod(p);
                }}
              >
                {monthLong(p)}
              </button>
            ))}
          </div>
        </Card>
      </div>
      <div className="mt-5">
        <Button onClick={send} loading={busy}>
          Прислать файл в чат
        </Button>
      </div>
    </>
  );
}

function Settings() {
  const { data, loading, set } = useResource<SettingsResponse>('settings', () => api.settings());
  const rates = useResource<RatesResponse>('rates', () => api.rates());
  const [sub, setSub] = useState<'rates' | null>(null);
  const [markup, setMarkup] = useState('');
  const [pwd, setPwd] = useState<boolean>(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  if (loading || !data) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;
  if (sub === 'rates') return <Rates onBack={() => setSub(null)} />;

  const aed = rates.data?.rates.find((r) => r.pair === 'AED/RUB');

  const saveMarkup = async () => {
    const value = Math.round(Number(markup.replace(',', '.')) * 1_000_000);
    if (!Number.isFinite(value)) return;
    setBusy(true);
    try {
      const res = await api.putSettings({ rate_markup_rub_per_aed_e6: value });
      set(res);
      haptic.success();
      toast({ text: 'Надбавка сохранена' });
      setMarkup('');
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Card>
        <MenuRow
          title="Надбавка к курсу"
          value={`${rate(data.rate_markup_rub_per_aed_e6)} ₽ за AED`}
          onClick={() => setMarkup(rate(data.rate_markup_rub_per_aed_e6))}
        />
        <MenuRow
          title="Курсы"
          value={aed ? `${rate(aed.rate_e6)} ₽/AED · ${timeDubai(aed.at)}` : ''}
          onClick={() => setSub('rates')}
        />
        <MenuRow
          title="Пароль PDF-выписок"
          value={data.mashreq_pdf_password_set ? 'задан' : 'не задан'}
          onClick={() => setPwd(true)}
        />
        <MenuRow title="Валюта итога" value={data.default_currency_view === 'RUB' ? 'Рубли' : data.default_currency_view} />
        <MenuRow title="Часовой пояс" value="Дубай" />
      </Card>
      <div className="mt-3 text-[12px] leading-4 text-hint">
        Версия {data.version} · копия базы {timeDubai(data.last_backup_at)}
      </div>

      {markup ? (
        <Sheet
          title="Надбавка к курсу"
          onClose={() => setMarkup('')}
          footer={
            <Button onClick={saveMarkup} loading={busy}>
              Готово
            </Button>
          }
        >
          <div className="flex h-[60px] items-center gap-2 rounded-inset bg-inset px-4">
            <input
              autoFocus
              inputMode="decimal"
              className="nums w-full text-[28px] font-semibold"
              value={markup}
              onChange={(e) => setMarkup(e.target.value)}
            />
            <span className="text-[17px] text-hint">₽ за AED</span>
          </div>
          <div className="mt-2 text-[13px] text-hint">Прибавляется к курсу из запасных источников</div>
        </Sheet>
      ) : null}

      {pwd ? (
        <Sheet
          title="Пароль PDF-выписок"
          onClose={() => setPwd(false)}
          footer={
            <Button
              onClick={() => {
                setPwd(false);
                toast({ text: 'Пароль сохранён' });
              }}
            >
              Сохранить
            </Button>
          }
        >
          <input
            autoFocus
            type="password"
            className="h-[52px] w-full rounded-inset bg-inset px-4 text-[16px] placeholder:text-hint"
            placeholder="Пароль из письма банка"
          />
        </Sheet>
      ) : null}
    </>
  );
}

function Rates({ onBack }: { onBack?: () => void } = {}) {
  const { data, loading, set } = useResource<RatesResponse>('rates', () => api.rates());
  const [busy, setBusy] = useState(false);
  if (loading || !data) return <span className="skeleton skeleton-wrap mt-4 block h-24 w-full rounded-card" />;

  const refresh = async () => {
    setBusy(true);
    try {
      set(await api.refreshRates());
      haptic.success();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {onBack ? (
        <button type="button" className="mb-3 text-[15px] font-medium text-blue" onClick={onBack}>
          ← Настройки
        </button>
      ) : null}
      <Card>
        {data.rates.map((r) => (
          <Row
            key={r.pair}
            title={r.pair.replace('/', ' → ')}
            subtitle={`${rateSource(r.source)} · ${timeDubai(r.at)}${r.stale ? ' · устарел' : ''}`}
            right={rate(r.rate_e6)}
          />
        ))}
      </Card>
      <div className="mt-3">
        <Button kind="secondary" onClick={refresh} loading={busy}>
          Обновить
        </Button>
      </div>
    </>
  );
}
