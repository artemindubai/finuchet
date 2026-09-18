import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { haptic, pushBackLayer, sheetMaxHeight } from '../app/telegram';

/** Шторка снизу — в ней живут все формы (DESIGN_SPEC 4.3). Свайп вниз закрывает. */
export function Sheet({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const [drag, setDrag] = useState(0);
  const startY = useRef<number | null>(null);
  const heightRef = useRef(0);
  const sheetRef = useRef<HTMLDivElement | null>(null);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    haptic.tap();
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Верхний слой для кнопки «Назад» Телеграма: вложенный список выбора закроется первым (4.7 п. 25).
    const release = pushBackLayer(() => closeRef.current());
    return () => {
      release();
      document.body.style.overflow = prev;
    };
  }, []);

  const onStart = (e: React.TouchEvent) => {
    startY.current = e.touches[0].clientY;
    heightRef.current = sheetRef.current?.offsetHeight ?? 1;
  };
  const onMove = (e: React.TouchEvent) => {
    if (startY.current === null) return;
    const dy = e.touches[0].clientY - startY.current;
    if (dy > 0) setDrag(dy);
  };
  const onEnd = () => {
    if (drag > heightRef.current * 0.3) onClose();
    setDrag(0);
    startY.current = null;
  };

  return (
    <div className="fixed inset-0 z-40 flex items-end">
      <div
        className="backdrop-enter absolute inset-0"
        style={{ background: 'rgba(0,0,0,.4)' }}
        onClick={onClose}
      />
      <div
        ref={sheetRef}
        className="sheet-enter relative w-full overflow-y-auto rounded-t-sheet bg-sheet px-4 pb-[calc(env(safe-area-inset-bottom)+16px)] pt-2"
        style={{ maxHeight: sheetMaxHeight(), transform: drag ? `translateY(${drag}px)` : undefined }}
        onTouchStart={onStart}
        onTouchMove={onMove}
        onTouchEnd={onEnd}
      >
        <div className="mx-auto mb-3 h-1 w-9 rounded-sm bg-separator" />
        <h2 className="mb-3 text-[17px] font-semibold">{title}</h2>
        {children}
        {footer ? <div className="mt-5">{footer}</div> : null}
      </div>
    </div>
  );
}

/** Второй слой той же шторки — список выбора, въезжает слева направо. */
export function PickerLayer({
  title,
  options,
  value,
  onPick,
  onClose,
  search = false,
}: {
  title: string;
  options: { value: string; label: string; hint?: string }[];
  value?: string | null;
  onPick: (v: string) => void;
  onClose: () => void;
  search?: boolean;
}) {
  const [q, setQ] = useState('');
  const list = search && q
    ? options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()))
    : options;
  return (
    <Sheet title={title} onClose={onClose}>
      {search || options.length > 10 ? (
        <input
          className="mb-2 h-[44px] w-full rounded-full bg-inset px-4 text-[16px] placeholder:text-hint"
          placeholder="Поиск"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      ) : null}
      <div className="max-h-[52vh] overflow-y-auto">
        {list.map((o) => (
          <button
            key={o.value}
            type="button"
            className="flex w-full items-center gap-3 py-3 text-left"
            onClick={() => {
              haptic.select();
              onPick(o.value);
            }}
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[17px]">{o.label}</span>
              {o.hint ? <span className="block truncate text-[13px] text-hint">{o.hint}</span> : null}
            </span>
            {o.value === value ? <span className="text-blue">✓</span> : null}
          </button>
        ))}
        {list.length === 0 ? <div className="pt-8 text-center text-[15px] text-hint">Ничего не нашлось</div> : null}
      </div>
    </Sheet>
  );
}
