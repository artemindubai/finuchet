import type { ReactNode } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { haptic } from '../app/telegram';

export function Screen({ children }: { children: ReactNode }) {
  return <div className="px-4 pb-[calc(var(--nav-h)+env(safe-area-inset-bottom)+24px)]">{children}</div>;
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-card bg-card p-4 ${className}`}>{children}</div>;
}

export function CardHead({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between">
      <h2 className="text-[17px] font-semibold leading-[22px]">{title}</h2>
      {action}
    </div>
  );
}

/** Заголовок корневого экрана. Высота 52 у всех четырёх — иначе заголовок прыгает при смене таба (m4). */
export function PageTitle({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="sticky top-0 z-20 -mx-4 flex h-[52px] items-center gap-2 bg-bg px-4">
      <h1 className="flex-1 text-[22px] font-bold leading-7 tracking-[-0.01em]">{title}</h1>
      {right}
    </div>
  );
}

export function SectionTitle({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="mb-3 mt-6 flex items-baseline justify-between">
      <h2 className="text-[22px] font-bold leading-7 tracking-[-0.01em]">{title}</h2>
      {right ? <span className="nums text-[15px] text-hint">{right}</span> : null}
    </div>
  );
}

/**
 * Заголовок группы счетов на Главной — 17/600, а не 22/700 (M14): слово «Рубли» не должно весить
 * больше остатка «132 000 ₽» (20/700). Порядок веса на экране: герой 40 → остатки 20 → группы 17.
 */
export function GroupTitle({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex items-baseline justify-between">
      <h2 className="text-[17px] font-semibold leading-[22px]">{title}</h2>
      {right ? <span className="nums text-[15px] text-hint">{right}</span> : null}
    </div>
  );
}

export function LinkAction({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      className="text-[15px] font-medium text-blue"
      onClick={() => {
        haptic.tap();
        onClick();
      }}
    >
      {children}
    </button>
  );
}

type ButtonKind = 'primary' | 'secondary' | 'danger';

export function Button({
  children,
  onClick,
  kind = 'primary',
  disabled = false,
  loading = false,
}: {
  children: ReactNode;
  onClick?: () => void;
  kind?: ButtonKind;
  disabled?: boolean;
  loading?: boolean;
}) {
  // Вторичная и опасная — на --c-inset-on-bg: на фоне страницы #F4F5F6 не отличался от фона (B4).
  const base = 'w-full rounded-btn text-[16px] font-semibold transition-colors duration-[80ms]';
  const style =
    kind === 'primary'
      ? 'h-[52px] bg-yellow text-onbtn active:bg-yellowpress'
      : kind === 'danger'
        ? 'h-12 rounded-inset bg-insetbg text-danger'
        : 'h-12 rounded-inset bg-insetbg text-blue';
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`${base} ${style} ${disabled ? 'bg-insetbg text-hint' : ''}`}
      onClick={() => {
        if (disabled || loading) return;
        haptic.tap();
        onClick?.();
      }}
    >
      {loading ? <Spinner /> : children}
    </button>
  );
}

function Spinner() {
  return (
    <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-onbtn border-t-transparent align-middle" />
  );
}

/** Чип-фильтр. Неактивный живёт на фоне страницы → дорожка --c-inset-on-bg (B4); «▾» — признак выбора (m1). */
export function Chip({
  children,
  active = false,
  onClick,
  onClear,
  caret = false,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  onClear?: () => void;
  caret?: boolean;
}) {
  return (
    <span
      className={`inline-flex h-[34px] shrink-0 items-center gap-1 rounded-full px-[14px] text-[13px] font-medium ${
        active ? 'bg-blue text-white' : 'bg-insetbg text-text'
      }`}
    >
      <button type="button" onClick={onClick} className="flex items-center gap-1 whitespace-nowrap">
        {children}
        {caret && !active ? <ChevronDown size={14} strokeWidth={2} className="text-hint" /> : null}
      </button>
      {active && onClear ? (
        <button type="button" onClick={onClear} aria-label="Сбросить фильтр" className="pl-0.5 text-white/90">
          ✕
        </button>
      ) : null}
    </span>
  );
}

export function Segment<T extends string>({
  options,
  value,
  onChange,
  full = false,
  onCard = false,
}: {
  options: { value: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  full?: boolean;
  /** Сегмент внутри белой карточки или шторки — там дорожка светлее (B4). */
  onCard?: boolean;
}) {
  return (
    <div
      className={`inline-flex h-9 items-center gap-0.5 rounded-full p-0.5 ${onCard ? 'bg-inset' : 'bg-insetbg'} ${
        full ? 'w-full' : ''
      }`}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-label={o.label}
          onClick={() => {
            haptic.select();
            onChange(o.value);
          }}
          className={`flex h-8 items-center justify-center rounded-full px-4 text-[15px] ${full ? 'flex-1' : ''} ${
            o.value === value ? 'bg-card font-semibold text-text' : 'font-medium text-hint'
          }`}
        >
          {o.icon ?? o.label}
        </button>
      ))}
    </div>
  );
}

export function Row({
  left,
  title,
  subtitle,
  right,
  rightSub,
  onClick,
  chevron = false,
  muted = false,
  wrap = false,
  indent = false,
}: {
  left?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
  rightSub?: ReactNode;
  onClick?: () => void;
  chevron?: boolean;
  muted?: boolean;
  wrap?: boolean;
  /** Строка без круга внутри карточки, где у соседей круг есть: держит одну левую колонку (M8). */
  indent?: boolean;
}) {
  // Левая и правая колонки выровнены по верху и имеют одну интерлиньяж-ступень (leading-5):
  // первые строки обеих колонок садятся на одну кэп-линию. Круг при этом центрирован по строке (M4).
  const body = (
    <div className="flex w-full items-center gap-3 py-2">
      {left}
      {indent && !left ? <span className="w-[44px] shrink-0" aria-hidden /> : null}
      <div className="flex min-w-0 flex-1 items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className={`truncate text-[16px] font-medium leading-5 ${muted ? 'text-hint' : ''}`}>{title}</div>
          {subtitle ? (
            <div className={`mt-0.5 text-[13px] leading-4 text-hint ${wrap ? '' : 'truncate'}`}>{subtitle}</div>
          ) : null}
        </div>
        {right || rightSub ? (
          <div className="shrink-0 text-right">
            {right ? <div className="nums text-[16px] font-medium leading-5">{right}</div> : null}
            {rightSub ? <div className="nums mt-0.5 text-[13px] leading-4 text-hint">{rightSub}</div> : null}
          </div>
        ) : null}
      </div>
      {chevron ? <ChevronRight size={18} className="shrink-0 text-hint" /> : null}
    </div>
  );
  if (!onClick) return body;
  return (
    <button
      type="button"
      className="-mx-2 w-[calc(100%+16px)] rounded-inset px-2 text-left transition-colors duration-[80ms] active:bg-inset"
      onClick={() => {
        haptic.tap();
        onClick();
      }}
    >
      {body}
    </button>
  );
}

/** Строка меню: шаг 56 по DESIGN_SPEC 4.2.5 — было 46, три разных ритма строки в приложении (m5). */
export function MenuRow({
  title,
  value,
  onClick,
}: {
  title: string;
  value?: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className="-mx-2 flex min-h-[56px] w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 text-left transition-colors duration-[80ms] active:bg-inset"
      onClick={() => {
        if (!onClick) return;
        haptic.tap();
        onClick();
      }}
    >
      <span className="min-w-0 flex-1 truncate text-[17px]">{title}</span>
      {value ? <span className="nums shrink-0 text-[15px] text-hint">{value}</span> : null}
      {onClick ? <ChevronRight size={18} className="shrink-0 text-hint" /> : null}
    </button>
  );
}

export function Empty({ text }: { text: string }) {
  return <div className="pt-8 text-center text-[15px] text-hint">{text}</div>;
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="pt-8 text-center">
      <div className="text-[15px] text-hint">Не удалось загрузить</div>
      <div className="mt-1 text-[15px] text-hint">Попробуйте ещё раз</div>
      <div className="mx-auto mt-4 max-w-[220px]">
        <Button kind="secondary" onClick={onRetry}>
          Повторить
        </Button>
      </div>
    </div>
  );
}

export function Header({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="sticky top-0 z-20 -mx-4 mb-1 flex h-[52px] items-center bg-bg px-4">
      <div className="w-10" />
      <div className="flex-1 truncate text-center text-[17px] font-semibold">{title}</div>
      <div className="flex w-10 justify-end">{right}</div>
    </div>
  );
}

/**
 * Полоса прогресса. Цвет задаётся снаружи (цвет категории у лимита, текстовый у цели) — синий здесь
 * означал бы «сюда можно нажать» и переставал быть цветом действия (M3). Дорожка — --c-inset-on-bg,
 * иначе на белой карточке её не видно (B4).
 */
export function ProgressBar({
  value,
  max,
  danger = false,
  color,
}: {
  value: number;
  max: number;
  danger?: boolean;
  color?: string;
}) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-insetbg">
      <div
        className="h-full rounded-full"
        style={{
          width: `${pct}%`,
          background: danger ? 'var(--c-danger)' : color ?? 'var(--c-text)',
          opacity: danger || color ? 1 : 0.85,
        }}
      />
    </div>
  );
}
