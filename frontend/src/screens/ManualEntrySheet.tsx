import { useMemo, useState } from 'react';
import { CalendarDays, ChevronRight } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache, useResource } from '../app/data';
import { dateLong } from '../lib/format';
import { today, yesterday } from '../lib/today';
import { Button, Segment } from '../components/ui';
import { PickerLayer, Sheet } from '../components/Sheet';
import { useToast } from '../components/Toast';
import { haptic } from '../app/telegram';
import type { Currency, Refs } from '../lib/types';

const KINDS = [
  { value: 'expense', label: 'Расход' },
  { value: 'income', label: 'Доход' },
  { value: 'transfer', label: 'Перевод' },
] as const;

const FAMILY_KINDS = [
  { value: 'family_withdrawal', label: 'Взял из семейного' },
  { value: 'family_repayment', label: 'Вернул в семейный' },
];

type Kind = (typeof KINDS)[number]['value'] | 'family_withdrawal' | 'family_repayment';
type Field = 'from' | 'to' | 'category' | 'source' | 'kind' | null;

function Picker({ label, value, onClick }: { label: string; value?: string | null; onClick: () => void }) {
  return (
    <button
      type="button"
      className="flex h-[52px] w-full items-center gap-3 rounded-inset bg-inset px-4 text-left"
      onClick={() => {
        haptic.tap();
        onClick();
      }}
    >
      <span className="min-w-0 flex-1">
        {value ? (
          <>
            <span className="block text-[12px] leading-4 text-hint">{label}</span>
            <span className="block truncate text-[16px] font-medium leading-5">{value}</span>
          </>
        ) : (
          <span className="block truncate text-[16px] text-hint">{label}</span>
        )}
      </span>
      <ChevronRight size={18} className="shrink-0 text-hint" />
    </button>
  );
}

export function ManualEntrySheet({ onClose, accountSlug }: { onClose: () => void; accountSlug?: string }) {
  const refs = useResource<Refs>('refs', () => api.refs());
  const [kind, setKind] = useState<Kind>('expense');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState<Currency>('AED');
  const [from, setFrom] = useState<string | null>(accountSlug ?? 'mashreq_personal');
  const [to, setTo] = useState<string | null>('tbank');
  const [category, setCategory] = useState<string | null>('exp_cafe');
  const [source, setSource] = useState<string | null>('inc_projects');
  const [opDate, setOpDate] = useState(today());
  const [comment, setComment] = useState('');
  const [field, setField] = useState<Field>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const accounts = useMemo(
    () => (refs.data?.accounts ?? []).filter((a) => a.is_money && !a.archived),
    [refs.data],
  );
  const nameBySlug = (slug: string | null) => accounts.find((a) => a.slug === slug)?.name ?? null;
  const catName = refs.data?.categories.find((c) => c.slug === category)?.name ?? null;
  const srcName = refs.data?.income_sources.find((s) => s.slug === source)?.name ?? null;

  const dayBefore = yesterday();
  const dayToday = today();

  const submit = async () => {
    const minor = Math.round(Number(amount.replace(',', '.')) * 100);
    if (!minor || minor <= 0) {
      toast({ text: 'Введите сумму' });
      return;
    }
    setBusy(true);
    try {
      await api.createEntry({
        kind,
        amount: minor,
        currency,
        from_account: kind === 'income' ? null : from,
        to_account: kind === 'expense' ? null : to,
        category: kind === 'expense' ? category : null,
        income_source: kind === 'income' ? source : null,
        op_date: opDate,
        description: comment,
      });
      dropCache('home');
      dropCache('entries');
      dropCache('account');
      haptic.success();
      toast({ text: 'Записано' });
      onClose();
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  if (field === 'kind') {
    return (
      <PickerLayer
        title="Тип операции"
        options={[...KINDS, ...FAMILY_KINDS].map((k) => ({ value: k.value, label: k.label }))}
        value={kind}
        onPick={(v) => {
          setKind(v as Kind);
          setField(null);
        }}
        onClose={() => setField(null)}
      />
    );
  }
  if (field === 'from' || field === 'to') {
    return (
      <PickerLayer
        title={field === 'from' ? 'Со счёта' : 'На счёт'}
        options={accounts.map((a) => ({ value: a.slug, label: a.name, hint: a.currency ?? undefined }))}
        value={field === 'from' ? from : to}
        onPick={(v) => {
          const acc = accounts.find((a) => a.slug === v);
          if (field === 'from') setFrom(v);
          else setTo(v);
          if (acc?.currency) setCurrency(acc.currency);
          setField(null);
        }}
        onClose={() => setField(null)}
      />
    );
  }
  if (field === 'category') {
    return (
      <PickerLayer
        title="Категория"
        search
        options={(refs.data?.categories ?? []).map((c) => ({ value: c.slug, label: c.name }))}
        value={category}
        onPick={(v) => {
          setCategory(v);
          setField(null);
        }}
        onClose={() => setField(null)}
      />
    );
  }
  if (field === 'source') {
    return (
      <PickerLayer
        title="Источник дохода"
        options={(refs.data?.income_sources ?? []).map((s) => ({ value: s.slug, label: s.name }))}
        value={source}
        onPick={(v) => {
          setSource(v);
          setField(null);
        }}
        onClose={() => setField(null)}
      />
    );
  }

  const isFamily = kind.startsWith('family');

  return (
    <Sheet
      title="Новая операция"
      onClose={onClose}
      footer={
        <Button onClick={submit} loading={busy}>
          Записать
        </Button>
      }
    >
      <div className="mb-3">
        {isFamily ? (
          <Picker label="Тип" value={FAMILY_KINDS.find((k) => k.value === kind)?.label} onClick={() => setField('kind')} />
        ) : (
          <Segment
            full
            onCard
            options={KINDS.map((k) => ({ value: k.value as Kind, label: k.label }))}
            value={kind}
            onChange={(v) => setKind(v)}
          />
        )}
      </div>

      <div className="mb-3 flex h-[60px] items-center gap-2 rounded-inset bg-inset px-4">
        <input
          inputMode="decimal"
          className="nums w-full text-[28px] font-semibold"
          placeholder="0"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <button
          type="button"
          className="text-[17px] font-medium text-hint"
          onClick={() => {
            const list: Currency[] = ['AED', 'RUB', 'USDT', 'USD'];
            setCurrency(list[(list.indexOf(currency) + 1) % list.length]);
            haptic.select();
          }}
        >
          {currency}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        {kind !== 'income' ? <Picker label="Со счёта" value={nameBySlug(from)} onClick={() => setField('from')} /> : null}
        {kind !== 'expense' ? <Picker label="На счёт" value={nameBySlug(to)} onClick={() => setField('to')} /> : null}
        {kind === 'expense' ? <Picker label="Категория" value={catName} onClick={() => setField('category')} /> : null}
        {kind === 'income' ? <Picker label="Источник" value={srcName} onClick={() => setField('source')} /> : null}

        {/* Дата была единственным полем формы без подложки — ритм формы рвался (m14).
            Теперь это такое же поле h 52, а быстрые чипы стоят над ним (DESIGN_SPEC 4.3). */}
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            className={`h-[34px] rounded-full px-[14px] text-[13px] font-medium ${
              opDate === dayToday ? 'bg-blue text-white' : 'bg-inset'
            }`}
            onClick={() => setOpDate(dayToday)}
          >
            Сегодня
          </button>
          <button
            type="button"
            className={`h-[34px] rounded-full px-[14px] text-[13px] font-medium ${
              opDate === dayBefore ? 'bg-blue text-white' : 'bg-inset'
            }`}
            onClick={() => setOpDate(dayBefore)}
          >
            Вчера
          </button>
        </div>
        <label className="relative flex h-[52px] w-full items-center gap-3 rounded-inset bg-inset px-4">
          <span className="min-w-0 flex-1">
            <span className="block text-[12px] leading-4 text-hint">Дата</span>
            <span className="block truncate text-[16px] font-medium leading-5">{dateLong(opDate)}</span>
          </span>
          <CalendarDays size={18} className="shrink-0 text-hint" />
          <input
            type="date"
            aria-label="Дата операции"
            className="absolute inset-0 h-full w-full opacity-0"
            value={opDate}
            onChange={(e) => e.target.value && setOpDate(e.target.value)}
          />
        </label>

        <input
          className="h-[52px] w-full rounded-inset bg-inset px-4 text-[16px] placeholder:text-hint"
          placeholder="Комментарий"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
    </Sheet>
  );
}
