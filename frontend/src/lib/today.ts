// Одна точка правды о «сегодня». На моках дата зафиксирована на 17.09.2026 — под их числа;
// с живым API берётся настоящая дата по Дубаю (UTC+4).
import { USE_MOCKS } from './api';
import { todayDubai } from './format';

const MOCK_TODAY = '2026-09-17';

export function today(): string {
  return USE_MOCKS ? MOCK_TODAY : todayDubai();
}

export function currentMonth(): string {
  return today().slice(0, 7);
}

/** Последние n месяцев, начиная с текущего: ['2026-09','2026-08',…] */
export function recentMonths(n: number): string[] {
  const [y, m] = currentMonth().split('-').map(Number);
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(Date.UTC(y, m - 1 - i, 1));
    out.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`);
  }
  return out;
}

export function yesterday(): string {
  return USE_MOCKS ? '2026-09-16' : todayDubai(-1);
}

/** Дата через n месяцев: '2026-09-17' + 3 → '2026-12-17' */
export function plusMonths(date: string, n: number): string {
  const [y, m, d] = date.split('-').map(Number);
  const shifted = new Date(Date.UTC(y, m - 1 + n, d));
  return shifted.toISOString().slice(0, 10);
}

/** Последний день месяца: '2026-09' → '2026-09-30' */
export function monthEnd(month: string): string {
  const [y, m] = month.split('-').map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${month}-${String(last).padStart(2, '0')}`;
}
