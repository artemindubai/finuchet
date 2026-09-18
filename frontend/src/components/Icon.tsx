import {
  ArrowLeftRight, Banknote, Bitcoin, Briefcase, Car, Clapperboard, Coffee, CreditCard,
  Dumbbell, FileText, Gift, GraduationCap, Heart, HeartPulse, Home, Landmark, MoreHorizontal,
  Plane, Receipt, Shirt, ShoppingCart, SlidersHorizontal, Sofa, Sun, User, Users, Wifi,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

// Ключи иконок приходят с сервера (accounts.icon, categories.icon) — свои фронт не выдумывает.
const MAP: Record<string, LucideIcon> = {
  cafe: Coffee,
  groceries: ShoppingCart,
  car: Car,
  home: Home,
  sofa: Sofa,
  wifi: Wifi,
  fun: Clapperboard,
  shirt: Shirt,
  health: HeartPulse,
  edu: GraduationCap,
  doc: FileText,
  plane: Plane,
  heart: Heart,
  gift: Gift,
  tax: Receipt,
  family: Users,
  dots: MoreHorizontal,
  adjust: SlidersHorizontal,
  swap: ArrowLeftRight,
  briefcase: Briefcase,
  sun: Sun,
  bank: Landmark, // банковский счёт — «колонны», не та же карта, что у кредитки (M9)
  cash: Banknote,
  card: CreditCard,
  credit: CreditCard,
  crypto: Bitcoin,
  person: User,
  sport: Dumbbell,
};

export function Glyph({ name, size = 20, color }: { name: string; size?: number; color?: string }) {
  const Cmp = MAP[name] ?? MoreHorizontal;
  return <Cmp size={size} strokeWidth={1.8} color={color} />;
}

/** Круглая цветная подложка — только у категорий и счетов (DESIGN_SPEC 4.2.5). */
export function CircleIcon({
  name,
  color,
  size = 40,
  ring = false,
  muted = false,
}: {
  name: string;
  color: string;
  size?: number;
  ring?: boolean;
  muted?: boolean;
}) {
  const glyph = Math.round(size * 0.5);
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full"
      style={{
        width: size,
        height: size,
        // Погашенная иконка отменённой операции: на --c-inset она сливалась с белой шторкой (m13).
        background: muted ? 'var(--c-inset-on-bg)' : color,
        boxShadow: ring ? 'inset 0 0 0 3px var(--c-card)' : undefined,
      }}
    >
      <Glyph name={name} size={glyph} color={muted ? 'var(--c-hint)' : '#FFFFFF'} />
    </span>
  );
}

export const CURRENCY_COLOR: Record<string, string> = {
  RUB: '#3E7BFA',
  AED: '#1FA855',
  USDT: '#00A88F',
  USD: '#3E7BFA',
};

const CASH_COLOR = '#7B8794';

// Иконка и цвет операции приходят с сервера в ленте (§5.5). В ответе одной операции
// этих полей в контракте нет — на такой случай запасная таблица по виду операции.
const KIND_LOOK: Record<string, { icon: string; color: string }> = {
  transfer: { icon: 'swap', color: '#7B8794' },
  exchange: { icon: 'swap', color: '#00A88F' },
  family_withdrawal: { icon: 'family', color: '#34B37E' },
  family_repayment: { icon: 'family', color: '#34B37E' },
  family_topup_by_parents: { icon: 'family', color: '#34B37E' },
  family_spent_own: { icon: 'family', color: '#34B37E' },
  own_contribution_to_family: { icon: 'family', color: '#1FA855' },
  paid_for_family_from_own: { icon: 'family', color: '#1FA855' },
  loan_given: { icon: 'person', color: '#5B6CD9' },
  loan_repaid_to_me: { icon: 'person', color: '#5B6CD9' },
  loan_taken: { icon: 'person', color: '#5B6CD9' },
  loan_repaid_by_me: { icon: 'person', color: '#5B6CD9' },
  tax_payment: { icon: 'tax', color: '#6E7781' },
  opening_balance: { icon: 'adjust', color: '#A0A7B0' },
  balance_correction: { icon: 'adjust', color: '#A0A7B0' },
  expense: { icon: 'dots', color: '#A0A7B0' },
  income: { icon: 'dots', color: '#A0A7B0' },
};

export function entryLook(kind: string, icon?: string | null, color?: string | null) {
  const fallback = KIND_LOOK[kind] ?? KIND_LOOK.expense;
  return { icon: icon || fallback.icon, color: color || fallback.color };
}

/** Цвет круга счёта: по валюте, наличные — серые (DESIGN_SPEC 4.2.3). */
export function accountColor(currency: string | null, icon: string): string {
  if (icon === 'cash') return CASH_COLOR;
  return CURRENCY_COLOR[currency ?? ''] ?? CASH_COLOR;
}

/**
 * Пиктограмма счёта — по ТИПУ счёта (DESIGN_SPEC 4.2.3, M9). Сервер шлёт `card` и банковскому
 * счёту, и кредитке, и на Главной выходила колонка одинаковых синих кругов.
 */
export function accountGlyph(a: { icon: string; type?: string; role?: string; currency?: string | null }): string {
  if (a.icon === 'cash') return 'cash';
  if (a.icon === 'crypto' || a.currency === 'USDT') return 'crypto';
  if (a.icon === 'credit' || a.type === 'liability' || a.role === 'liability') return 'credit';
  return 'bank';
}

/** Контурное кольцо: у семейных счетов (опека) и у кредитки — единственного счёта «в минус» (M9). */
export function accountRing(a: { type?: string; role?: string }): boolean {
  return a.type === 'asset_family' || a.type === 'liability' || a.role === 'liability';
}

/** Текст на цветной плашке: тёмный на светлой заливке, белый на тёмной (контраст ≥ 4.5). */
export function onColor(hex: string): string {
  const m = hex.replace('#', '');
  const int = parseInt(m.length === 3 ? m.split('').map((c) => c + c).join('') : m, 16);
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const lum =
    0.2126 * channel((int >> 16) & 255) + 0.7152 * channel((int >> 8) & 255) + 0.0722 * channel(int & 255);
  const withDark = (lum + 0.05) / 0.06;      // контраст к #17181A
  const withWhite = 1.05 / (lum + 0.05);     // контраст к белому
  return withDark >= withWhite ? '#17181A' : '#FFFFFF';
}
