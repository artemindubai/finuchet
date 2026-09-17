import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
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

export function SectionTitle({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="mb-3 mt-6 flex items-baseline justify-between">
      <h2 className="text-[22px] font-bold leading-7 tracking-[-0.01em]">{title}</h2>
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
  const base = 'w-full rounded-btn text-[16px] font-semibold transition-colors duration-[80ms]';
  const style =
    kind === 'primary'
      ? 'h-[52px] bg-yellow text-onbtn active:bg-yellowpress'
      : kind === 'danger'
        ? 'h-12 rounded-inset bg-inset text-danger'
        : 'h-12 rounded-inset bg-inset text-blue';
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`${base} ${style} ${disabled ? 'bg-inset text-hint' : ''}`}
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

export function Chip({
  children,
  active = false,
  onClick,
  onClear,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  onClear?: () => void;
}) {
  return (
    <span
      className={`inline-flex h-[34px] shrink-0 items-center gap-1 rounded-full px-[14px] text-[13px] font-medium ${
        active ? 'bg-blue text-white' : 'bg-inset text-text'
      }`}
    >
      <button type="button" onClick={onClick} className="whitespace-nowrap">
        {children}
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
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  full?: boolean;
}) {
  return (
    <div className={`inline-flex h-9 items-center gap-0.5 rounded-full bg-inset p-0.5 ${full ? 'w-full' : ''}`}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => {
            haptic.select();
            onChange(o.value);
          }}
          className={`h-8 rounded-full px-4 text-[15px] ${full ? 'flex-1' : ''} ${
            o.value === value ? 'bg-card font-semibold text-text' : 'font-medium text-hint'
          }`}
        >
          {o.label}
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
}) {
  const body = (
    <div className="flex w-full items-center gap-3 py-2">
      {left}
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
      className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-inset px-2 py-[13px] text-left transition-colors duration-[80ms] active:bg-inset"
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

export function ProgressBar({ value, max, danger = false }: { value: number; max: number; danger?: boolean }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-inset">
      <div
        className="h-full rounded-full"
        style={{ width: `${pct}%`, background: danger ? 'var(--c-danger)' : 'var(--c-blue)' }}
      />
    </div>
  );
}
