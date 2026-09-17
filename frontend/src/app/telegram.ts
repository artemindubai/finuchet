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
  const scheme = forced
    ?? app?.colorScheme
    ?? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', scheme);
  document.documentElement.style.colorScheme = scheme;

  const params = app?.themeParams ?? {};
  for (const [key, cssVar] of CSS_VARS) {
    const value = params[key];
    if (value) document.documentElement.style.setProperty(cssVar, value);
    else document.documentElement.style.removeProperty(cssVar);
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

let backHandler: (() => void) | null = null;

export function setBackButton(handler: (() => void) | null) {
  const app = tg();
  if (!app) return;
  if (backHandler) app.BackButton.offClick(backHandler);
  backHandler = handler;
  if (handler) {
    app.BackButton.onClick(handler);
    app.BackButton.show();
  } else {
    app.BackButton.hide();
  }
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
