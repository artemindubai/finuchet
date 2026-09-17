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
const OUT = path.resolve(HERE, arg('out', '../../design/shots/wave2'));

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
      // Уникальный параметр в query — иначе переход на тот же hash не перезагружает страницу
      // и состояние прошлого кадра (открытый подэкран, фильтр, шторка) попадает в следующий.
      const url = `${BASE}/?theme=${theme}&shot=${made}${shot.hash}`;
      await page.goto(url, { waitUntil: 'networkidle' });
      await sleep(350);
      if (shot.click) {
        const target = page.getByText(shot.click, { exact: true }).first();
        if (await target.count()) {
          await target.click();
          await sleep(400);
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
      const file = path.join(OUT, `${shot.name}_${theme === 'dark' ? 'тёмная' : 'светлая'}.png`);
      await page.screenshot({ path: file });
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
