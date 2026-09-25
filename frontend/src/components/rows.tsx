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
      <BankMark a={a} size={44} />
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

/** Знаки банков векторными фигурами, похожими на настоящие логотипы (25.09, Артём: «отрисуй через полигоны»). */
function Logo({ slug, size }: { slug: string; size: number }) {
  const s = size;
  if (slug === 'tbank') {
    // Жёлтый щит с тёмной «Т», как у Т-Банка.
    return (
      <svg width={s} height={s} viewBox="0 0 48 48" aria-hidden>
        <rect width="48" height="48" rx="24" fill="#FFDD2D" />
        <path d="M13 11h22v13.5c0 6.2-4.6 10.4-11 12.8-6.4-2.4-11-6.6-11-12.8z" fill="#FFFFFF" />
        <path d="M16.5 15.5h15v4.6h-5.2v12.2h-4.6V20.1h-5.2z" fill="#333333" />
      </svg>
    );
  }
  if (slug === 'sber' || slug === 'sber_credit') {
    // Зелёный круг с белой «галочкой» и дугами, как у Сбера.
    return (
      <svg width={s} height={s} viewBox="0 0 48 48" aria-hidden>
        <defs>
          <linearGradient id="sbg" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#F2E913" />
            <stop offset="0.35" stopColor="#21A038" />
            <stop offset="1" stopColor="#0FA8E0" />
          </linearGradient>
        </defs>
        <circle cx="24" cy="24" r="24" fill="url(#sbg)" />
        <circle cx="24" cy="24" r="13" fill="none" stroke="#FFFFFF" strokeWidth="3.4" strokeDasharray="60 22" transform="rotate(-30 24 24)" />
        <path d="M17.5 23.5l5 4.6 11-10.6" fill="none" stroke="#FFFFFF" strokeWidth="3.6" strokeLinecap="round" strokeLinejoin="round" />
        {slug === 'sber_credit' ? <circle cx="38" cy="38" r="7" fill="#E5484D" stroke="#FFFFFF" strokeWidth="2" /> : null}
      </svg>
    );
  }
  if (slug.startsWith('mashreq') || slug === 'kopilka_mashrek') {
    // Оранжевый с белым цветком-лотосом NEO, как у Машрека.
    return (
      <svg width={s} height={s} viewBox="0 0 48 48" aria-hidden>
        <rect width="48" height="48" rx="24" fill={slug === 'mashreq_family' ? '#E8590C' : '#FF6A13'} />
        <g fill="#FFFFFF">
          <path d="M24 33c-2.2-4.8-2.2-10.8 0-17 2.2 6.2 2.2 12.2 0 17z" />
          <path d="M22.8 33.2c-4.4-2.4-7.4-7-8-12.8 4.6 2.9 7.3 7.6 8 12.8z" />
          <path d="M25.2 33.2c4.4-2.4 7.4-7 8-12.8-4.6 2.9-7.3 7.6-8 12.8z" />
          <path d="M21.6 34c-4.8-.3-8.6-2.8-10.6-6.6 4.3.1 8 2.6 10.6 6.6z" />
          <path d="M26.4 34c4.8-.3 8.6-2.8 10.6-6.6-4.3.1-8 2.6-10.6 6.6z" />
        </g>
        {slug === 'kopilka_mashrek' ? <circle cx="38" cy="38" r="7" fill="#1FA855" stroke="#FFFFFF" strokeWidth="2" /> : null}
      </svg>
    );
  }
  if (slug === 'bybit') {
    // Чёрный с надписью BYBIT и оранжевой «I».
    return (
      <svg width={s} height={s} viewBox="0 0 48 48" aria-hidden>
        <rect width="48" height="48" rx="24" fill="#17181A" />
        <text x="24" y="28.5" textAnchor="middle" fontFamily="Onest, Arial, sans-serif" fontWeight="800" fontSize="11" fill="#FFFFFF">
          BYB<tspan fill="#F7A600">I</tspan>T
        </text>
      </svg>
    );
  }
  return null;
}

const LOGO_SLUGS = new Set(['tbank', 'sber', 'sber_credit', 'mashreq_personal', 'mashreq_family', 'kopilka_mashrek', 'bybit']);

export function BankMark({ a, size = 48 }: { a: AccountView; size?: number }) {
  if (!LOGO_SLUGS.has(a.slug)) {
    return <CircleIcon name={accountGlyph(a)} color={accountColor(a.currency, a.icon)} size={size} ring={accountRing(a)} />;
  }
  return <span className="flex shrink-0">{<Logo slug={a.slug} size={size} />}</span>;
}

/** Сумма крупно, копейки мельче и светлее — как в банковских приложениях. */
export function BigMoney({ v, className = '' }: { v: Money; className?: string }) {
  const s = money(v, 'none');
  const m = s.match(/^(.*?)(,\d{2})(\s.*)$/);
  if (!m) return <span className={`nums ${className}`}>{s}</span>;
  return (
    <span className={`nums ${className}`}>
      {m[1]}
      <span className="text-[0.62em] font-bold opacity-60">{m[2]}</span>
      {m[3]}
    </span>
  );
}

/** Счёт отдельной карточкой с воздухом (25.09: «сделай как Т-Банк»). */
export function AccountCard({ a, onClick }: { a: AccountView; onClick: (id: number) => void }) {
  const liability = a.role === 'liability';
  const shown = liability ? a.natural : a.balance;
  return (
    <button
      type="button"
      className="card-lift mt-3 flex w-full items-center gap-4 rounded-[24px] bg-card px-5 py-5 text-left transition-transform duration-100 active:scale-[0.985]"
      onClick={() => {
        haptic.tap();
        onClick(a.id);
      }}
    >
      <BankMark a={a} />
      <span className="min-w-0 flex-1">
        <BigMoney v={shown} className="block truncate text-[24px] font-extrabold leading-7 tracking-[-0.01em]" />
        <span className="mt-1 block truncate text-[15px] leading-5 text-hint">
          {liability && shown.amount > 0 ? `Долг · ${a.name}` : a.name}
        </span>
        {a.frozen ? (
          <span className="nums mt-2 inline-block rounded-full px-2.5 py-1 text-[12px] font-semibold leading-4" style={{ background: 'var(--c-frozen-bg)', color: 'var(--c-frozen)' }}>
            ❄ {moneyWhole(a.frozen, 'none')} под семейные
          </span>
        ) : null}
      </span>
    </button>
  );
}
