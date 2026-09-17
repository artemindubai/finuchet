import { useMemo } from 'react';
import { haptic } from '../app/telegram';
import { bp, money, monthTiny } from '../lib/format';
import { Glyph, onColor } from './Icon';
import type { Breakdown, Money } from '../lib/types';

/** Чип категории: заливка цветом категории, внутри круг 20 с пиктограммой и сумма. */
export function CategoryChip({
  name,
  color,
  icon,
  amount,
  onClick,
}: {
  name: string;
  color: string;
  icon?: string;
  amount: Money;
  onClick?: () => void;
}) {
  const ink = onColor(color);
  return (
    <button
      type="button"
      disabled={!onClick}
      className="flex h-[34px] items-center gap-1.5 overflow-hidden rounded-full pl-1.5 pr-3 disabled:cursor-default"
      style={{ background: color, color: ink }}
      onClick={() => {
        if (!onClick) return;
        haptic.tap();
        onClick();
      }}
    >
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
        style={{ background: ink === '#FFFFFF' ? 'rgba(255,255,255,.22)' : 'rgba(255,255,255,.55)' }}
      >
        <Glyph name={icon ?? 'dots'} size={13} color={ink} />
      </span>
      <span className="min-w-0 truncate text-[13px] font-medium">{name}</span>
      <span className="nums shrink-0 text-[13px] font-medium">{money(amount, 'none')}</span>
    </button>
  );
}

/** Составная полоса долей h8 r4 — приём tbank_newapp_01. */
export function ShareBar({ parts, height = 8 }: { parts: { color: string; share_bp: number }[]; height?: number }) {
  const total = parts.reduce((s, p) => s + p.share_bp, 0) || 1;
  return (
    <div className="flex w-full overflow-hidden rounded-full" style={{ height }}>
      {parts.map((p, i) => (
        <span key={i} style={{ width: `${(p.share_bp / total) * 100}%`, background: p.color }} />
      ))}
    </div>
  );
}

interface Slice {
  key: string;
  name: string;
  color: string;
  share_bp: number;
  amount: Money;
  category_id?: number;
}

function toSlices(rows: Breakdown[]): Slice[] {
  const big = rows.filter((r) => r.share_bp >= 500);
  const small = rows.filter((r) => r.share_bp < 500);
  const slices: Slice[] = big.map((r) => ({
    key: String(r.category_id ?? r.source_id ?? r.name),
    name: r.name,
    color: r.color,
    share_bp: r.share_bp,
    amount: r.amount,
    category_id: r.category_id,
  }));
  if (small.length) {
    slices.push({
      key: 'rest',
      name: 'Прочее',
      color: '#A0A7B0',
      share_bp: small.reduce((s, r) => s + r.share_bp, 0),
      amount: {
        amount: small.reduce((s, r) => s + r.amount.amount, 0),
        currency: small[0].amount.currency,
      },
    });
  }
  return slices.sort((a, b) => b.share_bp - a.share_bp);
}

/** Кольцо расходов: сегменты встык, дырка в цвете карточки, проценты снаружи у крупных долей. */
export function Donut({ rows, onPick }: { rows: Breakdown[]; onPick?: (categoryId: number) => void }) {
  const slices = useMemo(() => toSlices(rows), [rows]);
  const R = 74;
  const W = 52;
  const C = 130;
  const circumference = 2 * Math.PI * R;
  let offset = 0;
  const arcs = slices.map((s) => {
    const len = (s.share_bp / 10000) * circumference;
    const arc = { ...s, len, offset };
    offset += len;
    return arc;
  });
  let labelAngle = 0;

  return (
    // Поле по бокам — под подписи долей снаружи кольца, иначе «59 %» упирается в край.
    <svg viewBox="-35 0 330 260" className="mx-auto block w-full max-w-[330px]" role="img" aria-label="Доли по категориям">
      <g transform={`rotate(-90 ${C} ${C})`}>
        {arcs.map((a) => (
          <circle
            key={a.key}
            cx={C}
            cy={C}
            r={R}
            fill="none"
            stroke={a.color}
            strokeWidth={W}
            strokeDasharray={`${a.len} ${circumference - a.len}`}
            strokeDashoffset={-a.offset}
            onClick={() => {
              if (a.category_id && onPick) {
                haptic.tap();
                onPick(a.category_id);
              }
            }}
            style={{ cursor: a.category_id && onPick ? 'pointer' : undefined }}
          />
        ))}
      </g>
      {arcs.map((a) => {
        const mid = labelAngle + a.share_bp / 2;
        labelAngle += a.share_bp;
        if (a.share_bp < 800) return null;
        const rad = ((mid / 10000) * 360 - 90) * (Math.PI / 180);
        const x = C + Math.cos(rad) * 112;
        const y = C + Math.sin(rad) * 112;
        return (
          <text
            key={`l-${a.key}`}
            x={x}
            y={y}
            fontSize="13"
            fill="var(--c-hint)"
            textAnchor={x < C - 6 ? 'end' : x > C + 6 ? 'start' : 'middle'}
            dominantBaseline="middle"
          >
            {bp(a.share_bp)}
          </text>
        );
      })}
    </svg>
  );
}

export function DonutChips({
  rows,
  onPick,
  limit = 7,
}: {
  rows: Breakdown[];
  onPick?: (categoryId: number) => void;
  limit?: number;
}) {
  const shown = rows.slice(0, limit);
  const restCount = rows.length - shown.length;
  return (
    <div className="grid grid-cols-2 gap-2">
      {shown.map((r) => (
        <CategoryChip
          key={r.category_id ?? r.source_id ?? r.name}
          name={r.name}
          color={r.color}
          icon={r.icon}
          amount={r.amount}
          onClick={r.category_id && onPick ? () => onPick(r.category_id!) : undefined}
        />
      ))}
      {restCount > 0 ? (
        <span className="flex h-[34px] items-center justify-center rounded-full bg-inset text-[13px] font-medium text-hint">
          Ещё {restCount}
        </span>
      ) : null}
    </div>
  );
}

/** Двенадцать пар столбиков: доход зелёный, расход тёмный. Осей и сетки нет. */
export function MonthBars({
  data,
  selected,
  onSelect,
}: {
  data: { month: string; income: Money; expense: Money }[];
  selected: string;
  onSelect: (month: string) => void;
}) {
  const max = Math.max(1, ...data.flatMap((d) => [d.income.amount, d.expense.amount]));
  const H = 110;
  return (
    <div className="flex items-end justify-between gap-[9px]">
      {data.map((d, i) => {
        const active = d.month === selected;
        // Подписи через один, последний месяц и выбранный — всегда (DESIGN_SPEC 4.3).
        const labelled = active || (data.length - 1 - i) % 2 === 0;
        return (
          <button
            key={d.month}
            type="button"
            className="flex flex-1 flex-col items-center gap-1.5"
            onClick={() => {
              haptic.select();
              onSelect(d.month);
            }}
          >
            <span className="flex h-[110px] items-end gap-[2px]">
              <span
                className="w-2 rounded-t"
                style={{
                  height: Math.max(2, (d.expense.amount / max) * H),
                  background: 'var(--c-text)',
                  opacity: active ? 1 : 0.75,
                }}
              />
              <span
                className="w-2 rounded-t"
                style={{
                  height: Math.max(2, (d.income.amount / max) * H),
                  background: 'var(--c-income)',
                  opacity: active ? 1 : 0.75,
                }}
              />
            </span>
            <span className={`text-[11px] ${active ? 'font-semibold text-text' : 'text-hint'}`}>
              {labelled ? monthTiny(d.month) : ' '}
            </span>
          </button>
        );
      })}
    </div>
  );
}
