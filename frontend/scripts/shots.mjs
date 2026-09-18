// Снимки всех экранов в двух темах при 390x844.
// Запуск: npm run build && npm run preview  (в другом окне)  && node scripts/shots.mjs
// Либо: node scripts/shots.mjs --url http://127.0.0.1:4173 --out ../design/shots/wave2
import { chromium } from 'playwright';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
}

const BASE = arg('url', 'http://localhost:4173');
const OUT = path.resolve(HERE, arg('out', '../../design/shots/wave4'));
const ONLY = arg('only', '');

/** Каждый кадр: имя файла, хеш-маршрут и действия до снимка. */
const SHOTS = [
  { name: 'главная', hash: '#/' },
  { name: 'главная_низ', hash: '#/', scroll: 900 },
  { name: 'счёт', hash: '#/account/5' },
  { name: 'операции', hash: '#/entries' },
  { name: 'операции_фильтр', hash: '#/entries', click: 'Категории' },
  { name: 'операция', hash: '#/entry/431' },
  { name: 'операция_проводки', hash: '#/entry/431', click: 'Проводки' },
  { name: 'операция_расход', hash: '#/entry/412' },
  { name: 'операция_правка', hash: '#/entry/434' },
  { name: 'операция_отменённая', hash: '#/entry/399' },
  { name: 'аналитика', hash: '#/analytics' },
  { name: 'аналитика_низ', hash: '#/analytics', scroll: 900 },
  { name: 'аналитика_доходы', hash: '#/analytics', click: 'Доходы' },
  { name: 'ещё', hash: '#/more' },
  { name: 'ещё_долги', hash: '#/more', click: 'Долги' },
  { name: 'ещё_календарь', hash: '#/more', click: 'Календарь платежей' },
  { name: 'ещё_цели', hash: '#/more', click: 'Цели' },
  { name: 'ещё_лимиты', hash: '#/more', click: 'Лимиты' },
  { name: 'ещё_остатки', hash: '#/more', click: 'Начальные остатки' },
  { name: 'ещё_выгрузка', hash: '#/more', click: 'Выгрузка в таблицу' },
  { name: 'ещё_настройки', hash: '#/more', click: 'Настройки' },
  { name: 'шторка_новая_операция', hash: '#/entries', clickLabel: 'Добавить операцию' },

  // Состояния (M11): скелетон, пустая лента, ошибка загрузки, тост, нажатая строка, кнопка в загрузке.
  // Мок-сервер читает ?slow / ?empty / ?fail — переключатели живут только в моках.
  { name: 'состояние_скелетон_главная', hash: '#/', query: 'slow=4000', wait: 700, dir: 'states' },
  { name: 'состояние_скелетон_лента', hash: '#/entries', query: 'slow=4000', wait: 700, dir: 'states' },
  { name: 'состояние_пусто_лента', hash: '#/entries', query: 'empty=1', dir: 'states' },
  { name: 'состояние_ошибка', hash: '#/', query: 'fail=1', dir: 'states' },
  // Тоста при отмене больше нет: шторка сама показывает отмену, тост ложился поверх её же
  // кнопки «Вернуть» (Н10). Кадр снимает именно это состояние шторки.
  { name: 'состояние_шторка_отменена', hash: '#/entry/412', click: 'Отменить операцию', wait: 500, dir: 'states' },
  { name: 'состояние_нажатая_строка', hash: '#/', press: 'Т-Банк', dir: 'states' },
  { name: 'состояние_кнопка_загрузка', hash: '#/more', click: 'Выгрузка в таблицу',
    click2: 'Прислать файл в чат', query: 'slow=4000', wait: 350, dir: 'states' },
];

const THEMES = ['light', 'dark'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Свой Chromium Playwright, а если он не скачан — системный Chrome. */
async function launch() {
  try {
    return await chromium.launch();
  } catch {
    return await chromium.launch({ channel: 'chrome' });
  }
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    locale: 'ru-RU',
  });
  // Телеграмовский SDK снаружи клиента не нужен и тормозит съёмку.
  await context.route('**/telegram-web-app.js', (route) => route.fulfill({ body: '', contentType: 'application/javascript' }));

  const page = await context.newPage();
  let made = 0;

  for (const theme of THEMES) {
    for (const shot of SHOTS) {
      if (ONLY && !shot.name.includes(ONLY)) continue;
      // Уникальный параметр в query — иначе переход на тот же hash не перезагружает страницу
      // и состояние прошлого кадра (открытый подэкран, фильтр, шторка) попадает в следующий.
      const extra = shot.query ? `&${shot.query}` : '';
      const url = `${BASE}/?theme=${theme}&shot=${made}${extra}${shot.hash}`;
      // Со скелетоном networkidle ждать нечего — грузится сам мок, поэтому load.
      await page.goto(url, { waitUntil: shot.query ? 'load' : 'networkidle' });
      await sleep(shot.wait ?? 350);
      const tap = async (text) => {
        const target = page.getByText(text, { exact: true }).first();
        if (await target.count()) {
          await target.click();
          await sleep(400);
        }
      };
      if (shot.click) await tap(shot.click);
      if (shot.fill) {
        const row = page.locator('div', { hasText: shot.fill.label }).last();
        const input = row.locator('input').first();
        if (await input.count()) await input.fill(shot.fill.value);
      }
      if (shot.click2) await tap(shot.click2);
      if (shot.press) {
        // Нажатая строка: держим палец, кадр снимается в этом состоянии.
        const target = page.getByText(shot.press, { exact: true }).first();
        if (await target.count()) {
          const box = await target.boundingBox();
          if (box) {
            await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
            await page.mouse.down();
            await sleep(200);
          }
        }
      }
      if (shot.clickLabel) {
        const target = page.getByLabel(shot.clickLabel).first();
        if (await target.count()) {
          await target.click();
          await sleep(400);
        }
      }
      if (shot.scroll) {
        await page.mouse.wheel(0, shot.scroll);
        await sleep(300);
      }
      const dir = shot.dir ? path.join(OUT, shot.dir) : OUT;
      await mkdir(dir, { recursive: true });
      const file = path.join(dir, `${shot.name}_${theme === 'dark' ? 'тёмная' : 'светлая'}.png`);
      await page.screenshot({ path: file });
      if (shot.press) await page.mouse.up();
      made += 1;
      process.stdout.write(`${file}\n`);
    }
  }

  await browser.close();
  console.log(`готово: ${made} кадров`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
