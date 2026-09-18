import type { Money } from './types';

const NNBSP = ' '; // узкий неразрывный — разряды
const NBSP = ' '; // неразрывный — перед знаком валюты
export const MINUS = '−';

const SYMBOL: Record<string, string> = { RUB: '₽', USD: '$', AED: 'AED', USDT: 'USDT' };

const MONTHS_GEN = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];
const MONTHS_NOM = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];
const MONTHS_PREP = [
  'январе', 'феврале', 'марте', 'апреле', 'мае', 'июне',
  'июле', 'августе', 'сентябре', 'октябре', 'ноябре', 'декабре',
];

function groupDigits(whole: string): string {
  let out = '';
  for (let i = 0; i < whole.length; i++) {
    const left = whole.length - i;
    out += whole[i];
    if (left > 1 && left % 3 === 1) out += NNBSP;
  }
  return out;
}

/** Число без валюты: 184250 → «1 842,50», 13200000 → «132 000». */
export function num(minor: number): string {
  const sign = minor < 0 ? MINUS : '';
  const abs = Math.abs(minor);
  const whole = Math.floor(abs / 100).toString();
  const cents = abs % 100;
  const body = groupDigits(whole);
  return sign + (cents ? `${body},${cents.toString().padStart(2, '0')}` : body);
}

export type SignMode = 'auto' | 'none' | 'plus' | 'minus';

/** Деньги по правилам §5.3: разряды, запятая, нулевые копейки скрыты, валюта после числа. */
export function money(v: Money | null | undefined, sign: SignMode = 'auto'): string {
  if (!v) return '—';
  const symbol = SYMBOL[v.currency] ?? v.currency;
  const abs = Math.abs(v.amount);
  let prefix = '';
  if (sign === 'auto' && v.amount < 0) prefix = MINUS;
  if (sign === 'plus') prefix = '+';
  if (sign === 'minus') prefix = MINUS;
  return `${prefix}${num(abs)}${NBSP}${symbol}`;
}

/**
 * Агрегат (сумма нескольких операций) — целым числом, без копеек: DESIGN_SPEC 4.2.4, исключение M2.
 * Округление половины вверх по модулю. Копейки остаются у отдельной операции, в шторке и в траншах.
 */
export function moneyWhole(v: Money | null | undefined, sign: SignMode = 'auto'): string {
  if (!v) return '—';
  const abs = Math.abs(v.amount);
  const rounded = Math.floor((abs + 50) / 100) * 100;
  return money({ amount: v.amount < 0 ? -rounded : rounded, currency: v.currency }, sign);
}

export function moneyShort(v: Money | null | undefined): string {
  return money(v, 'none');
}

/** Курс: 24500000 → «24,50». */
export function rate(rateE6: number): string {
  const rounded = Math.round(rateE6 / 10000); // сотые
  return num(rounded);
}

export function bp(value: number): string {
  const percent = Math.round(value / 100);
  return `${percent}${NBSP}%`;
}

/** Доля без пробела — только для подписей вокруг кольца, где места нет (критик, m3). */
export function bpTight(value: number): string {
  return `${Math.round(value / 100)}%`;
}

export function bpExact(value: number): string {
  const whole = Math.floor(value / 100);
  const frac = value % 100;
  return frac ? `${whole},${Math.round(frac / 10)}${NBSP}%` : `${whole}${NBSP}%`;
}

const MONTHS_TINY = [
  'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
];

/** Год текущей даты по Дубаю — год в подписи ставим, только если он другой (M1). */
function currentYear(): number {
  return Number(todayDubai().slice(0, 4));
}

/** '2026-09-17' → «17 сентября»; прошлый год — «17 сентября 2025» (DESIGN_SPEC 4.2.4, M1). */
export function dateLong(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  const tail = y === currentYear() ? '' : `${NBSP}${y}`;
  return `${d}${NBSP}${MONTHS_GEN[m - 1]}${tail}`;
}

/** '2026-09-17' → «17 сен» — только для узкой правой колонки ленты (M1). */
export function dateTiny(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  const tail = y === currentYear() ? '' : `${NBSP}${String(y).slice(2)}`;
  return `${d}${NBSP}${MONTHS_TINY[m - 1]}${tail}`;
}

/**
 * Готовый текст сервера может нести дату числами («по 24,50 от 17.09.2026») — приводим к одному
 * формату показа (M1). Правится ТОЛЬКО показ, ответ API не трогается.
 */
export function humanizeDates(text: string | null | undefined): string {
  if (!text) return '';
  return text.replace(/\b(\d{1,2})\.(\d{2})(?:\.(\d{2,4}))?\b/g, (whole, d: string, m: string, y?: string) => {
    const mi = Number(m) - 1;
    if (mi < 0 || mi > 11) return whole;
    const year = y ? Number(y.length === 2 ? `20${y}` : y) : currentYear();
    const tail = year === currentYear() ? '' : `${NBSP}${year}`;
    return `${Number(d)}${NBSP}${MONTHS_GEN[mi]}${tail}`;
  });
}

/** '2026-09' → «Сентябрь 2026» */
export function monthLong(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return `${MONTHS_NOM[m - 1]}${NBSP}${y}`;
}

/** '2026-09' → «Сентябрь» (без года — для чипа-фильтра). */
export function monthNom(month: string): string {
  return MONTHS_NOM[Number(month.split('-')[1]) - 1];
}

/** '2026-09' → «Сен»; другой год — «Сен 2025». Короткий чип периода (m15). */
export function monthChip(month: string): string {
  const [y, m] = month.split('-').map(Number);
  const name = MONTHS_NOM[m - 1].slice(0, 3);
  return y === currentYear() ? name : `${name}${NBSP}${y}`;
}

/** '2026-09' → «сентябре» (для «Траты в сентябре») */
export function monthPrep(month: string): string {
  const m = Number(month.split('-')[1]);
  return MONTHS_PREP[m - 1];
}

/** '2026-09' → «сен» для подписи столбика */
export function monthTiny(month: string): string {
  const m = Number(month.split('-')[1]);
  return MONTHS_NOM[m - 1].slice(0, 3).toLowerCase();
}

/** ISO UTC → «14:32» по Дубаю (UTC+4). */
export function timeDubai(iso: string): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return '';
  const dubai = new Date(t.getTime() + 4 * 3600 * 1000);
  const hh = dubai.getUTCHours().toString().padStart(2, '0');
  const mm = dubai.getUTCMinutes().toString().padStart(2, '0');
  return `${hh}:${mm}`;
}

/** Сегодняшняя дата по Дубаю (UTC+4) — 'YYYY-MM-DD'. */
export function todayDubai(shift = 0): string {
  const now = new Date();
  const dubai = new Date(now.getTime() + 4 * 3600 * 1000 + shift * 86400000);
  return dubai.toISOString().slice(0, 10);
}

// Словарь источника курса — ровно слова DESIGN_SPEC 4.3 (критик, m8). «биржа», «er_api», «cache» —
// это ключи API, в интерфейсе они читались как отладочный вывод.
const RATE_SOURCE: Record<string, string> = {
  voice: 'назван голосом',
  manual: 'задан вручную',
  bybit_p2p: 'рынок',
  er_api: 'рынок',
  cbr: 'рынок',
  cache: 'рынок',
};

/** Источник курса по-русски: 'bybit_p2p' → «рынок», 'er_api+markup' → «рынок +2 ₽». */
export function rateSource(source: string, markupE6?: number): string {
  const [base, markup] = source.split('+');
  const word = RATE_SOURCE[base] ?? 'рынок';
  if (!markup) return word;
  return markupE6 ? `${word} +${rate(markupE6)}${NBSP}₽` : `${word} с надбавкой`;
}

const SOURCE_LABEL: Record<string, string> = {
  voice: 'голосом',
  text: 'текстом',
  manual: 'вручную',
  screenshot: 'со скрина',
  statement: 'из выписки',
  system: 'системой',
};

/** Первая буква заглавной: «взял на расходы» → «Взял на расходы». */
export function capitalize(text: string | null | undefined): string {
  if (!text) return '';
  return text[0].toUpperCase() + text.slice(1);
}

export function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source;
}

export function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few;
  return many;
}

export function daysLeftLabel(days: number): string {
  if (days === 0) return 'сегодня';
  if (days === 1) return 'завтра';
  if (days < 0) return `просрочено на ${-days}${NBSP}${plural(-days, 'день', 'дня', 'дней')}`;
  return `через ${days}${NBSP}${plural(days, 'день', 'дня', 'дней')}`;
}

export const REPEAT_LABEL: Record<string, string> = {
  once: 'разово',
  weekly: 'еженедельно',
  monthly: 'ежемесячно',
  quarterly: 'раз в квартал',
  yearly: 'раз в год',
};

export { NBSP, NNBSP };
