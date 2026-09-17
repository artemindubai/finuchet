import { useEffect, useState } from 'react';
import { useRoute, back, takeMoreSub } from './router';
import type { TabName } from './router';
import { setBackButton } from './telegram';
import { BottomNav } from '../components/BottomNav';
import { ToastHost } from '../components/Toast';
import { Home } from '../screens/Home';
import { Entries } from '../screens/Entries';
import { Analytics } from '../screens/Analytics';
import { More } from '../screens/More';
import { Account } from '../screens/Account';
import { EntrySheet } from '../screens/EntrySheet';
import { ManualEntrySheet } from '../screens/ManualEntrySheet';

type MoreSub = Parameters<typeof More>[0]['sub'];

export function App() {
  const route = useRoute();
  const [tab, setTab] = useState<TabName>('home');
  const [moreSub, setMoreSub] = useState<MoreSub>(null);
  const [addFor, setAddFor] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  useEffect(() => {
    if (route.name === 'home' || route.name === 'entries' || route.name === 'analytics' || route.name === 'more') {
      setTab(route.name);
    }
    if (route.name === 'more') {
      const requested = takeMoreSub();
      if (requested) setMoreSub(requested as MoreSub);
    }
  }, [route]);

  // Кнопка «Назад» Телеграма: закрывает верхний слой — шторку, подэкран, экран счёта.
  useEffect(() => {
    if (addOpen) {
      setBackButton(() => setAddOpen(false));
      return;
    }
    if (route.name === 'entry' || route.name === 'account') {
      setBackButton(() => back());
      return;
    }
    if (route.name === 'more' && moreSub) {
      setBackButton(() => setMoreSub(null));
      return;
    }
    setBackButton(null);
  }, [route, moreSub, addOpen]);

  const openAdd = (slug?: string) => {
    setAddFor(slug ?? null);
    setAddOpen(true);
  };

  const base = () => {
    if (route.name === 'account') return <Account id={route.id} onAdd={(slug) => openAdd(slug)} />;
    switch (tab) {
      case 'entries':
        return <Entries onAdd={() => openAdd()} />;
      case 'analytics':
        return <Analytics />;
      case 'more':
        return <More sub={moreSub} setSub={setMoreSub} />;
      default:
        return <Home />;
    }
  };

  return (
    <ToastHost>
      {base()}
      {route.name !== 'account' ? <BottomNav active={tab} /> : null}
      {route.name === 'entry' ? <EntrySheet id={route.id} onClose={() => back()} /> : null}
      {addOpen ? (
        <ManualEntrySheet accountSlug={addFor ?? undefined} onClose={() => setAddOpen(false)} />
      ) : null}
    </ToastHost>
  );
}
