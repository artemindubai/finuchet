// Хеш-роутер, шесть адресов из ARCHITECTURE §5.14.
import { useEffect, useState } from 'react';

export type Route =
  | { name: 'home' }
  | { name: 'entries' }
  | { name: 'analytics' }
  | { name: 'more' }
  | { name: 'account'; id: number }
  | { name: 'entry'; id: number };

export const TABS = ['home', 'entries', 'analytics', 'more'] as const;
export type TabName = (typeof TABS)[number];

const PATH: Record<TabName, string> = {
  home: '#/',
  entries: '#/entries',
  analytics: '#/analytics',
  more: '#/more',
};

export function parseHash(hash: string): Route {
  const h = hash.replace(/^#/, '');
  if (h === '' || h === '/') return { name: 'home' };
  const parts = h.split('/').filter(Boolean);
  if (parts[0] === 'entries') return { name: 'entries' };
  if (parts[0] === 'analytics') return { name: 'analytics' };
  if (parts[0] === 'more') return { name: 'more' };
  if (parts[0] === 'account' && parts[1]) return { name: 'account', id: Number(parts[1]) };
  if (parts[0] === 'entry' && parts[1]) return { name: 'entry', id: Number(parts[1]) };
  return { name: 'home' };
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    window.addEventListener('popstate', onChange);
    return () => {
      window.removeEventListener('hashchange', onChange);
      window.removeEventListener('popstate', onChange);
    };
  }, []);
  return route;
}

/** Табы не копятся в истории (replaceState), шторки и экраны — копятся (pushState). */
export function goTab(tab: TabName) {
  history.replaceState(null, '', PATH[tab]);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

// Подэкраны «Ещё» своих адресов не имеют (§5.14), поэтому нужный подэкран передаётся рядом с переходом.
let requestedMoreSub: string | null = null;

export function goMoreSub(sub: string) {
  requestedMoreSub = sub;
  goTab('more');
}

export function takeMoreSub(): string | null {
  const value = requestedMoreSub;
  requestedMoreSub = null;
  return value;
}

export function push(hash: string) {
  history.pushState(null, '', hash);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

export function back() {
  history.back();
}

export function openEntry(id: number) {
  push(`#/entry/${id}`);
}

export function openAccount(id: number) {
  push(`#/account/${id}`);
}
