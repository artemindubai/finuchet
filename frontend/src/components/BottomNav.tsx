import { List, Menu, PieChart, Wallet } from 'lucide-react';
import { goTab, TABS } from '../app/router';
import type { TabName } from '../app/router';
import { haptic } from '../app/telegram';

const ITEMS: { name: TabName; label: string; Icon: typeof Wallet }[] = [
  { name: 'home', label: 'Главная', Icon: Wallet },
  { name: 'entries', label: 'Операции', Icon: List },
  { name: 'analytics', label: 'Аналитика', Icon: PieChart },
  { name: 'more', label: 'Ещё', Icon: Menu },
];

export function BottomNav({ active }: { active: TabName }) {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-card"
      style={{ borderColor: 'var(--c-separator)', paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {ITEMS.map(({ name, label, Icon }) => {
        const on = TABS.includes(name) && name === active;
        return (
          <button
            key={name}
            type="button"
            className="flex h-14 flex-1 flex-col items-center justify-center gap-1"
            onClick={() => {
              haptic.select();
              goTab(name);
            }}
            aria-current={on ? 'page' : undefined}
          >
            <Icon size={24} strokeWidth={1.8} color={on ? 'var(--c-blue)' : 'var(--c-hint)'} />
            <span className={`text-[11px] font-medium leading-[14px] ${on ? 'text-blue' : 'text-hint'}`}>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
