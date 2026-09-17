import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

interface ToastState {
  text: string;
  action?: { label: string; run: () => void };
}

const Ctx = createContext<(t: ToastState) => void>(() => {});

export function useToast() {
  return useContext(Ctx);
}

export function ToastHost({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const show = useCallback((t: ToastState) => {
    setToast(t);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 2500);
  }, []);

  const value = useMemo(() => show, [show]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {toast ? (
        <div
          className="fixed inset-x-4 z-50 flex items-center gap-3 rounded-xl bg-text px-4 py-3 text-[15px] font-medium text-card"
          style={{ bottom: 'calc(var(--nav-h) + env(safe-area-inset-bottom) + 12px)' }}
          onClick={() => setToast(null)}
        >
          <span className="flex-1">{toast.text}</span>
          {toast.action ? (
            <button
              type="button"
              className="shrink-0 font-semibold"
              onClick={(e) => {
                e.stopPropagation();
                toast.action?.run();
                setToast(null);
              }}
            >
              {toast.action.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </Ctx.Provider>
  );
}
