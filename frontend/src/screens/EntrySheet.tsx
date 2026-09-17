import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { api } from '../lib/api';
import { dropCache } from '../app/data';
import { dateLong, money, rate, rateSource, sourceLabel, timeDubai } from '../lib/format';
import { Button } from '../components/ui';
import { Sheet } from '../components/Sheet';
import { CircleIcon, entryLook } from '../components/Icon';
import { TrancheRow } from '../components/rows';
import { useToast } from '../components/Toast';
import { haptic } from '../app/telegram';
import type { EntryFull } from '../lib/types';

const CURRENCY_SIGN: Record<string, string> = { RUB: '₽', USD: '$', AED: 'AED', USDT: 'USDT' };

/** 'AED/RUB' → «₽ за AED» */
function ratePair(pair: string): string {
  const [base, quote] = pair.split('/');
  return `${CURRENCY_SIGN[quote] ?? quote} за ${CURRENCY_SIGN[base] ?? base}`;
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <span className="shrink-0 text-[15px] text-hint">{label}</span>
      <span className="nums text-right text-[15px]">{value}</span>
    </div>
  );
}

export function EntrySheet({ id, onClose }: { id: number; onClose: () => void }) {
  const [entry, setEntry] = useState<EntryFull | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [amend, setAmend] = useState(false);
  const [amountText, setAmountText] = useState('');
  const toast = useToast();

  useEffect(() => {
    let alive = true;
    api
      .entry(id)
      .then((e) => alive && setEntry(e))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [id]);

  const refresh = () => {
    dropCache('home');
    dropCache('entries');
    dropCache('account');
  };

  const setStatus = async (next: 'void' | 'posted') => {
    if (!entry || busy) return;
    setBusy(true);
    const before = entry.status;
    setEntry({ ...entry, status: next }); // оптимистично
    try {
      const res = next === 'void' ? await api.voidEntry(entry.id) : await api.unvoidEntry(entry.id);
      setEntry({ ...entry, ...res, status: next });
      refresh();
      if (next === 'void') {
        haptic.warning();
        toast({ text: 'Операция отменена', action: { label: 'Вернуть', run: () => void setStatus('posted') } });
      } else {
        haptic.success();
        toast({ text: 'Операция возвращена' });
      }
    } catch {
      setEntry({ ...entry, status: before });
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  const saveAmend = async () => {
    if (!entry) return;
    const minor = Math.round(Number(amountText.replace(',', '.')) * 100);
    if (!minor || minor <= 0) return;
    setBusy(true);
    try {
      const res = await api.amendEntry(entry.id, { amount: minor });
      setEntry({ ...entry, ...res });
      refresh();
      haptic.success();
      setAmend(false);
      toast({ text: 'Поправлено' });
    } catch {
      haptic.error();
      toast({ text: 'Не сохранилось. Попробуйте ещё раз' });
    } finally {
      setBusy(false);
    }
  };

  if (failed) {
    return (
      <Sheet title="Операция" onClose={onClose}>
        <div className="py-6 text-center text-[15px] text-hint">Не удалось загрузить</div>
      </Sheet>
    );
  }

  if (!entry) {
    return (
      <Sheet title="Операция" onClose={onClose}>
        <div className="skeleton-wrap flex flex-col items-center gap-3 py-6">
          <span className="skeleton h-14 w-14 rounded-full" />
          <span className="skeleton h-8 w-40" />
          <span className="skeleton h-4 w-28" />
        </div>
      </Sheet>
    );
  }

  if (amend) {
    return (
      <Sheet
        title="Изменить сумму"
        onClose={() => setAmend(false)}
        footer={
          <Button onClick={saveAmend} loading={busy}>
            Сохранить
          </Button>
        }
      >
        <div className="flex h-[60px] items-center gap-2 rounded-inset bg-inset px-4">
          <input
            autoFocus
            inputMode="decimal"
            className="nums w-full text-[28px] font-semibold"
            placeholder="0"
            value={amountText}
            onChange={(e) => setAmountText(e.target.value)}
          />
          <span className="text-[17px] text-hint">{entry.amount.currency}</span>
        </div>
        <div className="mt-2 text-[13px] text-hint">Было {money(entry.amount, 'none')}</div>
      </Sheet>
    );
  }

  const isVoid = entry.status === 'void';
  const sign = entry.direction === 'in' ? 'plus' : entry.direction === 'out' ? 'minus' : 'none';
  // Что именно поменяла последняя правка — готовые строки от ядра (§5.5).
  const changes = entry.versions?.find((v) => v.version === entry.version)?.changed ?? [];
  const look = entryLook(entry.kind, entry.icon, entry.color);

  return (
    <Sheet
      title="Операция"
      onClose={onClose}
      footer={
        isVoid ? (
          <Button kind="secondary" onClick={() => void setStatus('posted')} loading={busy}>
            Вернуть
          </Button>
        ) : (
          <div className="flex flex-col gap-2">
            <Button
              kind="secondary"
              onClick={() => {
                setAmountText(String(entry.amount.amount / 100).replace('.', ','));
                setAmend(true);
              }}
            >
              Изменить
            </Button>
            <Button kind="danger" onClick={() => void setStatus('void')} loading={busy}>
              Отменить операцию
            </Button>
          </div>
        )
      }
    >
      {isVoid ? (
        <div className="pb-1 text-[13px] text-hint">Отменена {dateLong(entry.op_date)}</div>
      ) : null}

      <div className="flex flex-col items-center py-2">
        <CircleIcon name={look.icon} color={look.color} size={56} muted={isVoid} />
        <div
          className={`nums mt-3 text-[32px] font-bold leading-9 tracking-[-0.02em] ${
            isVoid ? 'text-hint line-through' : entry.direction === 'in' ? 'text-income' : ''
          }`}
        >
          {money(entry.amount, sign)}
        </div>
        <div className="mt-1 text-[13px] text-hint">{entry.title}</div>
      </div>

      <div className="mt-2 rounded-inset bg-inset px-4 py-1">
        <Fact label="Счёт" value={entry.subtitle} />
        <Fact label="Дата" value={dateLong(entry.op_date)} />
        {entry.rate ? (
          <Fact
            label="Курс"
            value={`${rate(entry.rate.rate_e6)} ${ratePair(entry.rate.pair)} · ${rateSource(entry.rate.source)}`}
          />
        ) : null}
        <Fact label="Записано" value={`${sourceLabel(entry.source)} в ${timeDubai(entry.created_at)}`} />
        {entry.description ? <Fact label="Комментарий" value={entry.description} /> : null}
        {entry.project ? <Fact label="Проект" value={entry.project} /> : null}
        {entry.counterparty ? <Fact label="Кому" value={entry.counterparty} /> : null}
        {entry.due_date ? <Fact label="Срок" value={dateLong(entry.due_date)} /> : null}
      </div>

      {entry.tranche ? (
        <div className="mt-3 rounded-inset bg-inset px-4 py-1">
          <TrancheRow t={entry.tranche} />
        </div>
      ) : null}

      <button
        type="button"
        className="mt-3 flex w-full items-center justify-between py-3"
        onClick={() => {
          haptic.tap();
          setOpen((v) => !v);
        }}
      >
        <span className="text-[16px] font-medium">Проводки</span>
        {open ? <ChevronUp size={20} className="text-hint" /> : <ChevronDown size={20} className="text-hint" />}
      </button>
      {open ? (
        <div className="rounded-inset bg-inset px-4 py-2">
          {entry.postings.map((p) => (
            <div key={p.seq} className="flex items-baseline gap-3 py-1.5">
              <span className="w-6 shrink-0 text-[15px] text-hint">{p.side === 'debit' ? 'Дт' : 'Кт'}</span>
              <span className="min-w-0 flex-1 truncate text-[15px]">{p.account_name}</span>
              <span className="nums shrink-0 text-[15px]">{money(p.amount, 'none')}</span>
            </div>
          ))}
        </div>
      ) : null}

      {entry.version > 1 ? (
        <div className="pt-3 text-[12px] leading-4 text-hint">
          Версия {entry.version}
          {changes.length ? ` · ${changes.join(', ')}` : ''}
        </div>
      ) : null}
    </Sheet>
  );
}
