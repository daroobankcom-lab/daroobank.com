/* Synthetic-only Chromium smoke tests. The server is Django's isolated test DB. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright-core');

const base = process.env.BROWSER_BASE_URL;
const author = process.env.BROWSER_AUTHOR;
const reviewer = process.env.BROWSER_REVIEWER;
const password = process.env.BROWSER_PASSWORD;
const ids = Object.fromEntries(['INGREDIENT', 'LEAF', 'FORMULATION', 'PRODUCT', 'PACKAGE']
  .map(key => [key.toLowerCase(), process.env['BROWSER_' + key]]));
assert(base && author && reviewer && password && Object.values(ids).every(Boolean), 'Missing synthetic test settings');
const parsedBase = new URL(base);
assert(parsedBase.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsedBase.hostname),
       'Only a loopback test server is allowed');
const origin = parsedBase.origin;

async function contextFor(browser, width, errors) {
  const context = await browser.newContext({viewport: {width, height: 900}, locale: 'fa-IR'});
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  // The fixture's example.org links are never fetched; abort any non-test origin.
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === origin ? route.continue() : route.abort();
  });
  return context;
}

async function checkLayout(page, label) {
  const state = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    dir: document.documentElement.dir,
  }));
  assert.equal(state.dir, 'rtl', label + ': missing RTL');
  assert(state.scrollWidth <= state.width, `${label}: horizontal overflow ${state.scrollWidth} > ${state.width}`);
}

async function login(page, username) {
  const response = await page.goto(base + '/staff/login/');
  assert.equal(response.status(), 200);
  assert.match(response.headers()['cache-control'], /no-store/);
  await page.locator('#id_username').focus();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'id_username');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'id_password');
  await page.locator('#id_username').fill(username);
  await page.locator('#id_password').fill(password);
  const [result] = await Promise.all([page.waitForResponse(r => r.url().includes('/staff/login/') && r.request().method() === 'POST'), page.locator('button[type=submit]').click()]);
  assert.equal(result.status(), 302, `login response ${result.status()}`);
  assert.equal(result.request().headers().origin, origin, 'login must retain a same-origin CSRF Origin');
  await page.waitForURL('**/staff/catalog/identity/');
}

async function revision(page, url, field, value) {
  let response = await page.goto(base + url);
  assert.equal(response.status(), 200);
  await page.locator(field).fill(value);
  await page.locator('#id_change_reason').fill('اصلاح ساختگی برای آزمون مرورگر');
  await page.locator('#id_synthetic_ack').check();
  const form = page.locator('form.staff-review-form');
  await Promise.all([page.waitForURL(/\/staff\/catalog\/identity\/[^/]+\/\d+\/$/), form.locator('button[type=submit]').click()]);
  return new URL(page.url()).pathname;
}

async function run() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'daroobank-chromium-'));
  let browser;
  try {
    // The npm package includes the libraries needed on lean Linux images. Extract
    // to an isolated temporary directory; do not modify system libraries.
    process.env.TMPDIR = temp;
    const chromiumEntry = require.resolve('@sparticuz/chromium');
    const archive = path.join(path.dirname(chromiumEntry), '..', 'bin', 'al2023.tar.br');
    const libRoot = path.join(temp, 'al2023');
    fs.mkdirSync(libRoot, {recursive: true});
    const tar = path.join(temp, 'libraries.tar');
    fs.writeFileSync(tar, zlib.brotliDecompressSync(fs.readFileSync(archive)));
    execFileSync('tar', ['-xf', tar, '-C', libRoot]);
    const libraryPath = path.join(libRoot, 'lib');
    const packed = (await import('@sparticuz/chromium')).default;
    // Keep normal same-origin enforcement. Browser sandbox is unavailable in this
    // container; never use this development-only runner with real data.
    const args = packed.args.filter(arg => !['--disable-web-security', '--allow-running-insecure-content',
                                             '--disable-site-isolation-trials', '--single-process', '--no-zygote',
                                             '--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process'].includes(arg));
    browser = await chromium.launch({executablePath: await packed.executablePath(), args, headless: true,
      env: {...process.env, LD_LIBRARY_PATH: [libraryPath, process.env.LD_LIBRARY_PATH || ''].filter(Boolean).join(':')}});
    const errors = [];
    for (const width of [320, 390, 768, 1440]) {
      const context = await contextFor(browser, width, errors);
      const page = await context.newPage();
      let response = await page.goto(base + '/');
      assert.equal(response.status(), 200);
      await checkLayout(page, `home ${width}`);
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement.className), 'skip-link');
      await page.locator('#drug-search').fill('Browser Synthetic Product');
      await Promise.all([page.waitForURL('**/search/?q=Browser*'), page.locator('form[role=search] button').click()]);
      assert.equal(page.url().includes('/search/'), true);
      assert.equal(await page.locator('.result-card').count(), 1);
      assert.match(await page.locator('.result-card').innerText(), /داروی عمومی ساختگی مرورگر/);
      assert(!((await page.locator('body').innerText()).includes('ماده ساختگی خصوصی مرورگر')));
      await checkLayout(page, `search ${width}`);
      response = await page.goto(base + '/prices/');
      assert.equal(response.status(), 200);
      await checkLayout(page, `prices ${width}`);
      response = await page.goto(base + `/staff/catalog/identity/ingredient/${ids.leaf}/lineage/`);
      assert.equal(response.status(), 200);
      assert(page.url().includes('/staff/login/'));
      assert.match(response.headers()['cache-control'], /no-store/);
      await login(page, author);
      response = await page.goto(base + `/staff/catalog/identity/formulation/${ids.formulation}/correction/`);
      assert.equal(response.status(), 200);
      await checkLayout(page, `identity form ${width}`);
      response = await page.goto(base + `/staff/catalog/identity/ingredient/${ids.leaf}/lineage/`);
      assert.equal(response.status(), 200);
      assert.match(response.headers()['x-robots-tag'], /noindex/);
      await checkLayout(page, `lineage ${width}`);
      await page.getByRole('link', {name: 'بررسی بخش بعدی'}).click();
      assert.match(await page.locator('body').innerText(), /گام ۲۱|گام 21/);
      await checkLayout(page, `lineage next ${width}`);
      await context.close();
    }
    const authorContext = await contextFor(browser, 390, errors);
    const page = await authorContext.newPage();
    await login(page, author);
    let child = await revision(page, `/staff/catalog/identity/ingredient/${ids.ingredient}/correction/`, '#id_name_fa', 'ماده اصلاحی ساختگی مرورگر');
    assert.match(child, /\/ingredient\/\d+\/$/);
    assert.match(await page.locator('body').innerText(), /ماده اصلاحی ساختگی مرورگر/);
    child = await revision(page, `/staff/catalog/identity/formulation/${ids.formulation}/correction/`, '#id_name', 'فرمول اصلاحی ساختگی مرورگر');
    assert.match(child, /\/formulation\/\d+\/$/);
    child = await revision(page, `/staff/catalog/identity/product/${ids.product}/correction/`, '#id_name', 'فرآورده اصلاحی ساختگی مرورگر');
    assert.match(child, /\/product\/\d+\/$/);
    const packagePath = await revision(page, `/staff/catalog/identity/package/${ids.package}/revise/`, '#id_quantity', '20');
    assert.match(packagePath, /\/package\/\d+\/$/);
    assert.equal(await page.locator('form[action$="/review/"]').count(), 0, 'author must not review own child');
    const firstContext = await contextFor(browser, 390, errors);
    const secondContext = await contextFor(browser, 390, errors);
    const first = await firstContext.newPage(), second = await secondContext.newPage();
    await login(first, reviewer); await login(second, reviewer);
    await first.goto(base + packagePath); await second.goto(base + packagePath);
    for (const reviewerPage of [first, second]) {
      await reviewerPage.locator('#id_decision').selectOption('defer');
      await reviewerPage.locator('#id_reason').fill('بازبینی مقدماتی ساختگی برای آزمایش');
    }
    await Promise.all([first.waitForURL(base + packagePath), first.locator('form[action$="/review/"] button').click()]);
    assert.match(await first.locator('body').innerText(), /بازبینی مقدماتی ساختگی/);
    const [conflict] = await Promise.all([
      second.waitForResponse(r => r.url().endsWith('/review/') && r.request().method() === 'POST'),
      second.locator('form[action$="/review/"] button').click(),
    ]);
    assert.equal(conflict.status(), 409);
    assert.match(await second.locator('body').innerText(), /صفحه را دوباره بارگذاری کنید/);
    assert.equal(await second.locator('form[action$="/review/"]').count(), 0);
    // An actual cross-origin navigation is intercepted before it leaves the test;
    // same-origin policy must not send the private staff URL to the destination.
    await first.evaluate(() => { const a = document.createElement('a'); a.href = 'https://example.org/privacy-test'; a.id = 'external-test'; a.textContent = 'External synthetic link'; document.body.append(a); });
    const [external] = await Promise.all([first.waitForRequest('https://example.org/privacy-test'), first.locator('#external-test').click()]);
    assert.equal(external.headers()['referer'], undefined);
    await firstContext.close(); await secondContext.close(); await authorContext.close();
    assert.deepEqual(errors, [], 'browser JavaScript errors');
    console.log(`browser checks passed (Chromium ${browser.version()}, widths 320/390/768/1440)`);
  } finally {
    if (browser) await browser.close();
    fs.rmSync(temp, {recursive: true, force: true});
  }
}
run().catch(error => { console.error(error.stack || String(error)); process.exitCode = 1; });
