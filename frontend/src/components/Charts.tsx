import { useMemo } from 'react';
import { haptic } from '../app/telegram';
import { bp, moneyWhole, monthLong, monthTiny } from '../lib/format';
import { dataColor, Glyph, onColor } from './Icon';
import type { Breakdown, Money } from '../lib/types';

/** Чип категории: заливка цветом категории, внутри круг 20 с пиктограммой и сумма. */
export function CategoryChip({
  name,
  color: raw,
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
  const color = dataColor(raw);
  const ink = onColor(color);
  // Чип по содержимому: имя не режется многоточием, сумма — целая (B3, M2).
  return (
    <button
      type="button"
      disabled={!onClick}
      className="flex h-[34px] max-w-full items-center gap-1.5 rounded-full pl-1.5 pr-3 disabled:cursor-default"
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
      <span className="nums shrink-0 text-[13px] font-medium">{moneyWhole(amount, 'none')}</span>
    </button>
  );
}

/** Составная полоса долей h8 r4 — приём tbank_newapp_01. */
export function ShareBar({ parts, height = 8 }: { parts: { color: string; share_bp: number }[]; height?: number }) {
  const total = parts.reduce((s, p) => s + p.share_bp, 0) || 1;
  return (
    <div className="flex w-full overflow-hidden rounded-full" style={{ height }}>
      {parts.map((p, i) => (
        <span key={i} style={{ width: `${(p.share_bp / total) * 100}%`, background: dataColor(p.color) }} />
      ))}
    </div>
  );
}

/** Цвет служебного сегмента «Остальное» (DESIGN_SPEC 4.3, M10). От темы не зависит, как и цвета категорий. */
const REST_COLOR = '#C4C9CF';

interface Slice {
  key: string;
  name: string;
  color: string;
  icon?: string;
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
    color: dataColor(r.color),
    icon: r.icon,
    share_bp: r.share_bp,
    amount: r.amount,
    category_id: r.category_id,
  }));
  if (small.length) {
    // «Прочее» — настоящая категория цвета #A0A7B0. Служебный сегмент зовётся «Остальное»
    // и красится в #C4C9CF, иначе на кольце два несмежных серых сегмента одного цвета (M10).
    slices.push({
      key: 'rest',
      name: 'Остальное',
      color: REST_COLOR,
      icon: 'dots',
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
            {/* Формат процента один на всё приложение: «24 %» и у кольца, и в списке под ним. Сжатое
                «24%» (m3) давало два формата на одном экране в 1000 px друг от друга (Н7). */}
            {bp(a.share_bp)}
          </text>
        );
      })}
    </svg>
  );
}

/**
 * Чипы повторяют группировку кольца ровно: столько же долей, те же имена, те же цвета, и служебный
 * сегмент назван «Остальное» со своей суммой. Прежние «семь + Ещё 4» давали на одном экране три
 * разные группировки одних данных, и самый заметный серый сегмент 9 % не был назван нигде (Н5).
 */
export function DonutChips({ rows, onPick }: { rows: Breakdown[]; onPick?: (categoryId: number) => void }) {
  const slices = useMemo(() => toSlices(rows), [rows]);
  // Чипы по содержимому с переносом, а не жёсткая сетка в две колонки: в колонке половинной
  // ширины имя категории резалось многоточием почти у каждого чипа (B3б).
  return (
    <div className="flex flex-wrap gap-2">
      {slices.map((s) => (
        <CategoryChip
          key={s.key}
          name={s.name}
          color={s.color}
          icon={s.icon}
          amount={s.amount}
          onClick={s.category_id && onPick ? () => onPick(s.category_id!) : undefined}
        />
      ))}
    </div>
  );
}

/**
 * Двенадцать пар столбиков. Расход — нейтральный `--c-bar` в ОБЕИХ темах: на `--c-text` он
 * в тёмной становился почти белым и перевешивал зелёный доход, то есть акцент инвертировался
 * при смене темы (M7а). Строка значений стоит НАД графиком (DESIGN_SPEC 4.3, M7в).
 */
export function MonthBars({
  data,
  selected,
  onSelect,
  caption = true,
}: {
  data: { month: string; income: Money; expense: Money }[];
  selected: string;
  onSelect: (month: string) => void;
  caption?: boolean;
}) {
  // Месяцы без данных не занимают слот: раньше двенадцать слотов делили ширину карточки, столбики
  // жались вправо, а над пустой левой третью висели подписи «ноя» и «янв» (Н6). Шаг пары считается
  // от месяцев с данными; выбранный месяц остаётся в ряду, даже если в нём пусто.
  const shown = useMemo(() => {
    const withData = data.filter((d) => d.income.amount > 0 || d.expense.amount > 0 || d.month === selected);
    return withData.length ? withData : data;
  }, [data, selected]);
  const max = Math.max(1, ...shown.flatMap((d) => [d.income.amount, d.expense.amount]));
  const H = 110;
  const current = shown.find((d) => d.month === selected);
  return (
    <>
    {caption && current ? (
      <div className="mb-3 text-[13px] leading-4 text-hint">
        {monthLong(current.month)} · доходы{' '}
        <span className="nums text-text">{moneyWhole(current.income, 'none')}</span> · расходы{' '}
        <span className="nums text-text">{moneyWhole(current.expense, 'none')}</span>
      </div>
    ) : null}
    <div className="flex items-end justify-between gap-[9px]">
      {shown.map((d, i) => {
        const active = d.month === selected;
        // Подписи через один, последний месяц и выбранный — всегда (DESIGN_SPEC 4.3).
        const labelled = active || (shown.length - 1 - i) % 2 === 0;
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
              <Bar value={d.expense.amount} max={max} h={H} color="var(--c-bar)" active={active} />
              <Bar value={d.income.amount} max={max} h={H} color="var(--c-income)" active={active} />
            </span>
            <span className={`text-[11px] ${active ? 'font-semibold text-text' : 'text-hint'}`}>
              {labelled ? monthTiny(d.month) : ' '}
            </span>
          </button>
        );
      })}
    </div>
    </>
  );
}

/**
 * Столбик месяца. Месяц без данных не рисуется вовсе (M7б): огрызки в 2–3 px у самой оси
 * читались как мусор, а не как «данных нет».
 */
function Bar({
  value, max, h, color, active,
}: { value: number; max: number; h: number; color: string; active: boolean }) {
  if (value <= 0) return <span className="w-2" />;
  return (
    <span
      className="w-2 rounded-t"
      style={{ height: Math.max(3, (value / max) * h), background: color, opacity: active ? 1 : 0.75 }}
    />
  );
}
