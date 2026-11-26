// Renders sheet.html to site/setup-sheet.pdf (US Letter, one page).
// Run from the repo root: node docs/setup-sheet/make-pdf.js  (needs Playwright)
const path = require('path');
const { chromium } = require('playwright');
(async () => {
  const dir = __dirname;
  const b = await chromium.launch(); const p = await b.newPage();
  await p.goto('file://' + path.join(dir, 'sheet.html'), { waitUntil: 'networkidle' });
  await p.evaluate(() => document.fonts.ready);
  const [scroll, client] = await p.evaluate(() => [document.body.scrollHeight, document.body.clientHeight]);
  if (scroll > client) console.warn(`Sheet overflows one page by ${scroll - client}px`);
  await p.pdf({ path: path.join(dir, '..', '..', 'site', 'setup-sheet.pdf'),
                format: 'Letter', printBackground: true, preferCSSPageSize: true });
  await b.close();
})();
