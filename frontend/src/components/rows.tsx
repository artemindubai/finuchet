import { accountColor, accountGlyph, accountRing, CircleIcon } from './Icon';
import { capitalize, dateLong, dateTiny, money, moneyWhole, rate, rateSource, sourceLabel } from '../lib/format';
import { haptic } from '../app/telegram';
import type { AccountView, EntryShort, Money, TrancheView } from '../lib/types';

function tail(e: EntryShort): string {
  const marks: string[] = [];
  if (e.source === 'voice') marks.push('голосом');
  else if (e.source === 'screenshot' || e.source === 'statement') marks.push(sourceLabel(e.source));
  if (e.version > 1) marks.push('правка');
  return marks.join(' · ');
}

// У перевода и обмена счета — это и есть содержание строки, у остальных видов счёт виден
// в шторке и в шапке экрана счёта. Подпись из трёх фактов обрезалась на третьем (критик, B3а).
const SUBTITLE_KEEPS_ACCOUNTS = new Set(['transfer', 'exchange']);

/** Строка операции: круг 40, два слоя текста, сумма справа (DESIGN_SPEC 4.3). */
export function EntryRow({ e, onClick }: { e: EntryShort; onClick: (id: number) => void }) {
  const isVoid = e.status === 'void';
  const name = capitalize(e.description) || e.title;
  // У перевода счета и есть содержание строки — слово «Перевод» его только дублирует
  // (стрелка и круг уже сказали это), а третий факт всё равно обрезался (B3а).
  const keepAccounts = SUBTITLE_KEEPS_ACCOUNTS.has(e.kind);
  const sub = [
    keepAccounts ? e.subtitle : e.description ? e.title : null,
    tail(e),
  ].filter(Boolean).join(' · ');
  const amountText = money(e.amount, e.direction === 'in' ? 'plus' : e.direction === 'out' ? 'minus' : 'none');
  return (
    <button
      type="button"
      className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 py-3 text-left transition-colors duration-[80ms] active:bg-inset"
      onClick={() => {
        haptic.tap();
        onClick(e.id);
      }}
    >
      <CircleIcon name={e.icon} color={e.color} muted={isVoid} />
      <span className="min-w-0 flex-1">
        <span className={`block truncate text-[16px] font-medium leading-5 ${isVoid ? 'text-hint' : ''}`}>{name}</span>
        <span className="mt-0.5 block truncate text-[13px] leading-4 text-hint">{sub}</span>
      </span>
      <span className="shrink-0 text-right">
        <span
          className={`nums block text-[16px] font-medium leading-5 ${
            isVoid ? 'text-hint line-through' : e.direction === 'in' ? 'text-income' : ''
          }`}
        >
          {amountText}
        </span>
        <span className="nums mt-0.5 block text-[13px] leading-4 text-hint">
          {isVoid ? 'отменена' : dateTiny(e.op_date)}
        </span>
      </span>
    </button>
  );
}

/**
 * День в ленте. Лента — ОДНА поверхность на весь список (B1): карточка на каждый день давала
 * стопку одинаковых скруглённых плашек с зазором 53 CSS, и на экран влезало шесть строк вместо
 * девяти в образце `sb_ios_40`. Заголовок дня — строка внутри этой поверхности, между днями
 * воздух 24 без разрыва фона. Итог дня «—», если трат в этот день не было (m11): пустое место
 * там, где глаз ждёт число, рвёт колонку итогов.
 *
 * Итога нет вовсе, когда в дне ровно одна операция: её сумма стоит строкой ниже, и одно и то же
 * число печаталось дважды в 40 px по вертикали — на «Счёте» три дня подряд (Н4).
 */
export function DayBlock({
  title,
  total,
  totalIn,
  items,
  first = false,
  onOpen,
}: {
  title: string;
  total?: Money | null;
  totalIn?: Money | null;
  items: EntryShort[];
  first?: boolean;
  onOpen: (id: number) => void;
}) {
  const single = items.length === 1;
  const sum =
    total && total.amount > 0
      ? moneyWhole(total, 'minus')
      : totalIn && totalIn.amount > 0
        ? moneyWhole(totalIn, 'plus')
        : '—';
  return (
    <section className={first ? '' : 'mt-6'}>
      <div className="mb-1 flex items-baseline justify-between">
        <h2 className="text-[17px] font-bold leading-[22px]">{title}</h2>
        {single ? null : <span className="nums text-[15px] leading-5 text-hint">{sum}</span>}
      </div>
      {items.map((e) => (
        <EntryRow key={e.id} e={e} onClick={onOpen} />
      ))}
    </section>
  );
}

/** Строка счёта в группе: круг 44 в цвете валюты, остаток сверху, имя снизу. */
export function AccountRow({ a, onClick }: { a: AccountView; onClick: (id: number) => void }) {
  const liability = a.role === 'liability';
  const shown = liability ? a.natural : a.balance;
  return (
    <button
      type="button"
      className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 py-2.5 text-left transition-colors duration-[80ms] active:bg-inset"
      onClick={() => {
        haptic.tap();
        onClick(a.id);
      }}
    >
      <CircleIcon
        name={accountGlyph(a)}
        color={accountColor(a.currency, a.icon)}
        size={44}
        ring={accountRing(a)}
      />
      <span className="min-w-0 flex-1">
        <span className="nums block truncate text-[20px] font-bold leading-6">{money(shown, 'none')}</span>
        <span className="mt-0.5 block truncate text-[13px] leading-4 text-hint">
          {liability && shown.amount > 0 ? `Долг · ${a.name}` : a.name}
        </span>
      </span>
      {a.frozen ? (
        <span className="nums shrink-0 rounded-lg px-2 py-1.5 text-[13px] leading-4" style={{ background: 'var(--c-frozen-bg)', color: 'var(--c-frozen)' }}>
          заморожено {moneyWhole(a.frozen, 'none')}
        </span>
      ) : null}
    </button>
  );
}

/** Строка транша заморозки: сколько рублей, за сколько дирхамов, по какому курсу, откуда курс. */
export function TrancheRow({
  t,
  onClick,
  compact = false,
}: {
  t: TrancheView;
  onClick?: (entryId: number) => void;
  compact?: boolean;
}) {
  const partial = t.rub_frozen && t.rub_left.amount < t.rub_frozen.amount;
  const body = (
    <div className="flex w-full items-start gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="nums text-[16px] font-medium leading-5">
          {partial && t.rub_frozen
            ? `${money(t.rub_left, 'none')} из ${money(t.rub_frozen, 'none')}`
            : money(t.rub_left, 'none')}
        </div>
        <div className="mt-0.5 text-[13px] leading-4 text-hint">
          в счёт {money(t.aed_left, 'none')} от {dateLong(t.op_date)}
          {compact ? '' : ` по ${rate(t.rate_e6)}`}
        </div>
        {partial && t.rub_frozen ? (
          <div className="mt-2 h-1 w-full overflow-hidden rounded-sm" style={{ background: 'var(--c-frozen-bg)' }}>
            <div
              className="h-full rounded-sm"
              style={{
                width: `${Math.round((t.rub_left.amount / t.rub_frozen.amount) * 100)}%`,
                background: 'var(--c-frozen)',
              }}
            />
          </div>
        ) : null}
      </div>
      {compact ? null : (
        <div className="shrink-0 pt-0.5 text-[13px] leading-4 text-hint">{rateSource(t.rate_source)}</div>
      )}
    </div>
  );
  if (!onClick || !t.entry_id) return body;
  return (
    <button
      type="button"
      className="-mx-2 w-[calc(100%+16px)] rounded-inset px-2 text-left transition-colors duration-[80ms] active:bg-inset"
      onClick={() => {
        haptic.tap();
        onClick(t.entry_id!);
      }}
    >
      {body}
    </button>
  );
}
