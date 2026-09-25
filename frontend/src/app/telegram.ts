// Мост к Telegram WebApp SDK: тема, кнопка «Назад», тактильный отклик (DESIGN_SPEC 4.2.1, 4.5).

interface ThemeParams {
  bg_color?: string;
  secondary_bg_color?: string;
  text_color?: string;
  hint_color?: string;
  section_separator_color?: string;
}

interface WebApp {
  initData: string;
  colorScheme: 'light' | 'dark';
  themeParams: ThemeParams;
  viewportStableHeight?: number;
  ready(): void;
  expand(): void;
  onEvent(event: string, handler: () => void): void;
  offEvent(event: string, handler: () => void): void;
  BackButton: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: {
    impactOccurred(style: string): void;
    notificationOccurred(type: string): void;
    selectionChanged(): void;
  };
}

export function tg(): WebApp | null {
  return (window as any).Telegram?.WebApp ?? null;
}

const CSS_VARS: [keyof ThemeParams, string][] = [
  ['bg_color', '--tg-theme-bg-color'],
  ['secondary_bg_color', '--tg-theme-secondary-bg-color'],
  ['text_color', '--tg-theme-text-color'],
  ['hint_color', '--tg-theme-hint-color'],
];

function forcedTheme(): 'light' | 'dark' | null {
  const value = new URLSearchParams(window.location.search).get('theme');
  return value === 'dark' || value === 'light' ? value : null;
}

function applyTheme() {
  const app = tg();
  const forced = forcedTheme();
  // 25.09 Артём: светлая тема по умолчанию, как в Т-Банке, даже если Телеграм тёмный. Тёмная — только ?theme=dark.
  const scheme = forced ?? 'light';
  document.documentElement.setAttribute('data-theme', scheme);
  document.documentElement.style.colorScheme = scheme;

  // Цвета Телеграма берём только в тёмной теме: в светлой тёмные themeParams перекрасили бы экран.
  const params = scheme === 'dark' ? (app?.themeParams ?? {}) : {};
  for (const [key, cssVar] of CSS_VARS) {
    const value = (params as Record<string, string | undefined>)[key];
    if (value) document.documentElement.style.setProperty(cssVar, value);
    else document.documentElement.style.removeProperty(cssVar);
  }
  const ui = app as unknown as { setHeaderColor?: (c: string) => void; setBackgroundColor?: (c: string) => void } | null;
  if (scheme === 'light') {
    try {
      ui?.setHeaderColor?.('#f2f3f5');
      ui?.setBackgroundColor?.('#f2f3f5');
    } catch {
      /* старый клиент Телеграма без этих методов */
    }
  }
}

export function initTelegram() {
  const app = tg();
  applyTheme();
  if (app) {
    app.ready();
    app.expand();
    app.onEvent('themeChanged', applyTheme);
  } else {
    window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', applyTheme);
  }
}

/**
 * Кнопка «Назад» Телеграма закрывает ВЕРХНИЙ слой (DESIGN_SPEC 4.5). Слои копятся стопкой:
 * базовый ставит App (экран счёта, подэкран «Ещё», шторка операции), поверх регистрируется
 * каждая открытая шторка. Без стопки вложенный слой выбора счёта/категории кнопкой «Назад»
 * не закрывался — чек-лист 4.7 п. 25 (отчёт агента C, «незакрытое в v1»).
 */
let baseBack: (() => void) | null = null;
const layers: (() => void)[] = [];
let attached: (() => void) | null = null;
let shown = false;

function top(): (() => void) | null {
  return layers.length ? layers[layers.length - 1] : baseBack;
}

function apply() {
  const app = tg();
  if (!app) return;
  if (attached) app.BackButton.offClick(attached);
  const handler = top();
  attached = handler ? () => handler() : null;
  // show()/hide() дёргаем только на смене состояния: старые клиенты на каждый вызов пишут
  // в консоль «BackButton is not supported in version 6.0».
  if (attached) {
    app.BackButton.onClick(attached);
    if (!shown) {
      app.BackButton.show();
      shown = true;
    }
  } else if (shown) {
    app.BackButton.hide();
    shown = false;
  }
}

export function setBackButton(handler: (() => void) | null) {
  baseBack = handler;
  apply();
}

/** Регистрирует слой; возвращает функцию снятия. Зовётся из Sheet на монтировании. */
export function pushBackLayer(handler: () => void): () => void {
  layers.push(handler);
  apply();
  return () => {
    const i = layers.lastIndexOf(handler);
    if (i >= 0) layers.splice(i, 1);
    apply();
  };
}

export const haptic = {
  select() {
    tg()?.HapticFeedback?.selectionChanged();
  },
  tap() {
    tg()?.HapticFeedback?.impactOccurred('light');
  },
  success() {
    tg()?.HapticFeedback?.notificationOccurred('success');
  },
  warning() {
    tg()?.HapticFeedback?.notificationOccurred('warning');
  },
  error() {
    tg()?.HapticFeedback?.notificationOccurred('error');
  },
};

export function sheetMaxHeight(): string {
  const h = tg()?.viewportStableHeight;
  return h ? `${Math.round(h * 0.9)}px` : '90vh';
}
