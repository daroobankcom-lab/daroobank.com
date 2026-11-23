/* Synthetic-only Chromium smoke tests. The server is Django's isolated test DB. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright-core');
const AxeBuilder = require('@axe-core/playwright').default;

const base = process.env.BROWSER_BASE_URL;
const author = process.env.BROWSER_AUTHOR;
const reviewer = process.env.BROWSER_REVIEWER;
const password = process.env.BROWSER_PASSWORD;
const ids = Object.fromEntries(['INGREDIENT', 'LEAF', 'FORMULATION', 'PRODUCT', 'PACKAGE', 'CLINICAL_LEAF', 'PRICE', 'RECEIPT', 'CLAIM', 'CANDIDATE']
  .map(key => [key.toLowerCase(), process.env['BROWSER_' + key]]));
assert(base && author && reviewer && password && Object.values(ids).every(Boolean), 'Missing synthetic test settings');
const parsedBase = new URL(base);
assert(parsedBase.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(parsedBase.hostname),
       'Only a loopback test server is allowed');
const origin = parsedBase.origin;

async function contextFor(browser, width, errors, options = {}) {
  const context = await browser.newContext({viewport: {width, height: 900}, locale: 'fa-IR', ...options});
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
  if (state.scrollWidth > state.width) {
    // Report geometry and selectors only; never print page content or form values.
    const offenders = await page.evaluate(() => [...document.querySelectorAll('body *')].map(el => {
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el), parent = el.parentElement && getComputedStyle(el.parentElement);
      return {tag: el.tagName, id: el.id.slice(0, 80), className: typeof el.className === 'string' ? el.className.slice(0, 120) : '',
              left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
              client: el.clientWidth, scroll: el.scrollWidth, cssWidth: style.width, cssMax: style.maxWidth,
              parentDisplay: parent && parent.display, parentColumns: parent && parent.gridTemplateColumns};
    }).filter(el => el.right > document.documentElement.clientWidth + 1 || el.left < -1)
      .slice(0, 12));
    assert.fail(`${label}: horizontal overflow ${state.scrollWidth} > ${state.width}; elements=${JSON.stringify(offenders)}`);
  }
}

function rgb(value) {
  const match = /^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/.exec(value);
  assert(match, `Expected opaque RGB, got ${value}`);
  return match.slice(1).map(Number);
}
function luminance(value) {
  const channels = rgb(value).map(n => { const x = n / 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
function ratio(a, b) { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
function blendOn(color, background) {
  // Forced colors can expose a partially transparent system outline color.
  const match = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\)$/.exec(color);
  if (!match) return color;
  const back = rgb(background), alpha = Number(match[4]);
  const result = match.slice(1, 4).map((n, i) => Math.round(Number(n) * alpha + back[i] * (1 - alpha)));
  return `rgb(${result.join(', ')})`;
}

async function checkScanIdSyntax(page, label) {
  const input = page.locator('#after');
  assert.equal(await input.getAttribute('type'), 'text');
  assert.equal(await input.getAttribute('inputmode'), 'numeric');
  assert.equal(await input.getAttribute('aria-describedby'), 'after-hint');
  assert.match(await page.locator('#after-hint').innerText(), /ارقام فارسی، عربی یا انگلیسی/);
  for (const [value, expected] of [['0', true], ['0001', true], ['۱2٣', true], ['١', true],
                                    ['۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۷', true], ['9223372036854775807', true],
                                    ['9223372036854775808', true], ['', false], ['1e2', false],
                                    ['१', false], ['12345678901234567890', false]]) {
    await input.fill(value);
    assert.equal(await input.inputValue(), value, `${label}: input precision`);
    assert.equal(await input.evaluate(element => element.validity.valid), expected, `${label}: syntax for ${value}`);
  }
  // Native constraint validation stops an exponent from submitting the form.
  await input.fill('1e2');
  const blocked = await input.evaluate(element => {
    let invalid = false, submitted = false;
    const onInvalid = () => { invalid = true; };
    const onSubmit = event => { submitted = true; event.preventDefault(); };
    element.addEventListener('invalid', onInvalid);
    element.form.addEventListener('submit', onSubmit);
    element.form.requestSubmit();
    element.removeEventListener('invalid', onInvalid);
    element.form.removeEventListener('submit', onSubmit);
    return {invalid, submitted};
  });
  assert.deepEqual(blocked, {invalid: true, submitted: false}, `${label}: invalid ID submitted`);
  await input.fill('0');
}

async function submitLocalizedScan(page, value) {
  const pathname = new URL(page.url()).pathname;
  await page.locator('#after').fill(value);
  const [response] = await Promise.all([
    page.waitForResponse(result => {
      const url = new URL(result.url());
      return result.request().method() === 'GET' && url.pathname === pathname && url.searchParams.get('after') === value;
    }),
    page.locator('#after').press('Enter'),
  ]);
  assert.equal(response.status(), 200);
  await page.waitForLoadState('load');
  assert.equal(await page.locator('#after').inputValue(), '0');
}

async function checkStaffScanError(page, label, width) {
  const pathname = new URL(page.url()).pathname;
  const params = new URLSearchParams({after: '9223372036854775808', category: 'synthetic-canary<script>'});
  const response = await page.goto(base + pathname + '?' + params);
  assert.equal(response.status(), 400);
  assert.match(response.headers()['cache-control'], /no-store/);
  assert.equal(response.headers()['referrer-policy'], 'same-origin');
  assert.match(response.headers()['x-robots-tag'], /noindex, nofollow/);
  assert.match(await page.locator('h1').innerText(), /درخواست بازرسی معتبر نیست/);
  assert(!(await page.locator('body').innerText()).includes('synthetic-canary'));
  await checkLayout(page, `${label} error ${width}`);
  if (width === 390) await auditAccessibility(page, `${label} error`);
  const restart = page.getByRole('link', {name: 'بازگشت و شروع دوباره ←'});
  assert.equal(await restart.getAttribute('href'), pathname);
  await restart.focus();
  await Promise.all([
    page.waitForURL(url => url.pathname === pathname && url.search === ''),
    page.keyboard.press('Enter'),
  ]);
  assert.equal(await page.locator('#after').inputValue(), '0');
}

// Reduce active-element diagnostics to fixed categories; never print page values or URLs.
async function focusRegion(page, selector) {
  return page.evaluate(selector => {
    const active = document.activeElement;
    if (!active) return 'none';
    if (active.matches(selector)) return 'expected';
    if (active.matches('.skip-link')) return 'skip';
    if (active.matches('main#main')) return 'main';
    if (active === document.body) return 'body';
    if (active.closest('header')) return 'header';
    if (active.closest('footer')) return 'footer';
    if (active.closest('main#main')) return 'other-main';
    return 'other';
  }, selector);
}

// Exercise actual keyboard and same-document fragment navigation, not .focus().
// Audit tools must not run between the keypresses; they may themselves move focus.
async function checkSkipLink(page, label, selector, timeout = 5000) {
  await page.keyboard.press('Tab');
  assert(await page.locator('.skip-link').evaluate(el => el === document.activeElement), `${label}: initial focus`);
  assert.equal(await page.locator('.skip-link').getAttribute('href'), '#main', `${label}: target`);
  assert(await page.locator('.skip-link').evaluate(el => {
    const rect = el.getBoundingClientRect(), css = getComputedStyle(el);
    return el.matches(':focus-visible') && css.visibility === 'visible' && css.display !== 'none' &&
      Number(css.opacity) > 0 && rect.width > 0 && rect.height > 0 && rect.top >= 0 &&
      rect.bottom <= innerHeight && rect.left >= 0 && rect.right <= innerWidth;
  }), `${label}: visible focus`);
  await checkKeyboardFocus(page, '.skip-link', label, '.skip-link');
  const pathname = new URL(page.url()).pathname;
  try {
    // Waiting for the fragment avoids racing a following Tab against navigation.
    await Promise.all([page.waitForURL(url => url.pathname === pathname && url.hash === '#main', {timeout}),
                       page.keyboard.press('Enter')]);
  } catch (error) {
    if (error.name === 'TimeoutError') assert.fail(`${label}: fragment navigation`);
    throw error;
  }
  try {
    // Native fragment navigation must actually focus the target, not just update
    // the address. Do not programmatically focus it on behalf of the user.
    await page.waitForFunction(() => document.activeElement === document.querySelector('main#main'), null, {timeout});
  } catch (error) {
    if (error.name === 'TimeoutError') assert.fail(`${label}: main focus (${await focusRegion(page, selector)})`);
    throw error;
  }
  await page.keyboard.press('Tab');
  if (!(await page.locator(selector).evaluate(el => el === document.activeElement && !!el.closest('main#main')))) {
    assert.fail(`${label}: next focus (${await focusRegion(page, selector)})`);
  }
}

async function checkKeyboardFocus(page, selector, label, container) {
  const state = await page.locator(selector).evaluate((element, container) => {
    const style = getComputedStyle(element);
    return {active: element === document.activeElement, visible: element.matches(':focus-visible'),
      outline: style.outlineStyle, width: parseFloat(style.outlineWidth), color: style.outlineColor,
      background: getComputedStyle(element.closest(container)).backgroundColor};
  }, container);
  assert(state.active && state.visible, `${label}: not keyboard-focused`);
  assert(state.outline !== 'none' && state.width >= 2, `${label}: missing focus outline`);
  assert(ratio(blendOn(state.color, state.background), state.background) >= 3,
         `${label}: outline contrast below 3:1 against container`);
}

// Selected plain-text elements on opaque, non-image surfaces only. Refuse
// layers/opacity that would make this simple foreground/background test unsound.
async function checkTextContrast(page, selector, containerSelector, label) {
  const state = await page.locator(selector).first().evaluate((element, containerSelector) => {
    const container = element.closest(containerSelector);
    if (!container) throw new Error(`Missing contrast container ${containerSelector}`);
    let node = element, reached = false;
    while (node) {
      const style = getComputedStyle(node);
      if (style.opacity !== '1' || style.filter !== 'none' || style.mixBlendMode !== 'normal') {
        throw new Error('Contrast needs review for opacity, filter or blending');
      }
      if (!reached) {
        if (style.backgroundImage !== 'none') throw new Error('Contrast needs review for background images');
        if (node !== container && style.backgroundColor !== 'rgba(0, 0, 0, 0)') {
          throw new Error('Contrast needs review for an intermediate background');
        }
        if (node === container) reached = true;
      }
      node = node.parentElement;
    }
    return {color: getComputedStyle(element).color, background: getComputedStyle(container).backgroundColor};
  }, containerSelector);
  assert(ratio(state.color, state.background) >= 4.5, `${label}: text contrast below 4.5:1`);
}

// Axe cannot reliably infer contrast through a gradient. Check these known
// text colors against both opaque gradient endpoints; changes to the gradient
// structure or transparency deliberately require a fresh review.
async function checkHeroContrast(page) {
  const values = await page.evaluate(() => {
    const style = selector => getComputedStyle(document.querySelector(selector));
    return {
      background: style('.hero').backgroundImage,
      colors: ['.hero-lead', '.hint-label', '.search-hint', '.hero-status span:not(.status-icon)']
        .map(selector => [selector, style(selector).color]),
      placeholder: getComputedStyle(document.querySelector('#drug-search'), '::placeholder').color,
      inputBackground: style('.search-form').backgroundColor,
    };
  });
  assert.equal(ratio('rgb(0, 0, 0)', 'rgb(255, 255, 255)'), 21);
  const gradient = /^linear-gradient\([^,]+,\s*(rgb\(\d+,\s*\d+,\s*\d+\))\s+[\d.]+%,\s*(rgb\(\d+,\s*\d+,\s*\d+\))\s+[\d.]+%\)$/.exec(values.background);
  assert(gradient, 'Hero needs exactly one two-stop opaque linear gradient; review any change');
  const stops = gradient.slice(1);
  const [first, second] = stops.map(rgb);
  assert(first.every((v, i) => v >= second[i]) || first.every((v, i) => v <= second[i]),
         'Non-monotonic gradient needs a new manual contrast review');
  for (const [selector, color] of values.colors) {
    const foreground = luminance(color), backgrounds = stops.map(luminance);
    assert(backgrounds.every(value => foreground < value) || backgrounds.every(value => foreground > value),
           `${selector} foreground lies inside gradient luminance range`);
    for (const background of stops) assert(ratio(color, background) >= 4.5, `${selector} contrast below 4.5:1`);
  }
  assert(ratio(values.placeholder, values.inputBackground) >= 4.5, 'search placeholder contrast below 4.5:1');
}

async function auditAccessibility(page, label) {
  const result = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
  const violations = result.violations.map(v => ({id: v.id, impact: v.impact,
    nodes: v.nodes.map(n => ({target: n.target, summary: n.failureSummary}))}));
  assert.deepEqual(violations, [], label + ': automated accessibility violations');
  const incomplete = result.incomplete.map(item => item.id + ':' + JSON.stringify(item.nodes.map(n => n.target)));
  console.log(`axe ${label}: ${incomplete.length} rules require manual review${incomplete.length ? ' (' + incomplete.join(', ') + ')' : ''}`);
}

async function login(page, username) {
  const response = await page.goto(base + '/staff/login/');
  assert.equal(response.status(), 200);
  assert.match(response.headers()['cache-control'], /no-store/);
  await page.locator('#id_username').focus();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'id_username');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'id_password');
  await checkKeyboardFocus(page, '#id_password', 'login password', '.staff-login-card');
  await page.locator('#id_username').fill(username);
  await page.locator('#id_password').fill(password);
  await page.keyboard.press('Tab');
  await checkKeyboardFocus(page, '.staff-login-form button[type=submit]', 'login submit', '.staff-login-card');
  const [result] = await Promise.all([page.waitForResponse(r => r.url().includes('/staff/login/') && r.request().method() === 'POST'), page.keyboard.press('Enter')]);
  assert.equal(result.status(), 302, `login response ${result.status()}`);
  assert.equal(result.request().headers().origin, origin, 'login must retain a same-origin CSRF Origin');
  await page.waitForURL('**/staff/');
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
                                             '--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process',
                                             '--in-process-gpu', '--ignore-gpu-blocklist', '--use-gl=angle',
                                             '--use-angle=swiftshader', '--enable-unsafe-swiftshader'].includes(arg));
    // This SSR smoke suite needs no GPU/WebGL. Software rendering avoided repeatable
    // intermittent startup crashes in the local lean Linux container; it does not
    // establish GPU rendering correctness or guarantee stability on other hosts.
    args.push('--disable-gpu');
    browser = await chromium.launch({executablePath: await packed.executablePath(), args, headless: true,
      env: {...process.env, LD_LIBRARY_PATH: [libraryPath, process.env.LD_LIBRARY_PATH || ''].filter(Boolean).join(':')}});
    const errors = [];
    for (const width of [320, 390, 768, 1440]) {
      const context = await contextFor(browser, width, errors);
      const page = await context.newPage();
      let response = await page.goto(base + '/');
      assert.equal(response.status(), 200);
      await checkLayout(page, `home ${width}`);
      await checkSkipLink(page, `skip home ${width}`, '#drug-search');
      await checkKeyboardFocus(page, '#drug-search', `search ${width}`, '.search-form');
      if (width === 390) {
        await auditAccessibility(page, 'home'); await checkHeroContrast(page);
        await checkTextContrast(page, '.eyebrow', '.eyebrow', 'hero eyebrow');
        await checkTextContrast(page, '.art-card-top small', '.art-card', 'art card caption');
        await checkTextContrast(page, '.label-one small', '.float-label', 'first art label caption');
        await checkTextContrast(page, '.label-two small', '.float-label', 'second art label caption');
        const lowContrast = await page.addStyleTag({content: '.eyebrow { color: #e3f4eb !important; }'});
        await assert.rejects(checkTextContrast(page, '.eyebrow', '.eyebrow', 'mutated eyebrow'), /contrast below/);
        await lowContrast.evaluate(el => el.remove());
        const broken = await context.newPage();
        await broken.goto(base + '/');
        await broken.locator('.skip-link').evaluate(el => el.setAttribute('href', '#wrong'));
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search'), /skip home 390: target/);
        await broken.goto(base + '/');
        await broken.locator('.skip-link').evaluate(el => el.setAttribute('tabindex', '-1'));
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search'), /skip home 390: initial focus/);
        await broken.goto(base + '/');
        await broken.addStyleTag({content: '.skip-link:focus { transform: translateY(-200%) !important; }'});
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search'), /skip home 390: visible focus/);
        await broken.goto(base + '/');
        await broken.locator('#drug-search').evaluate(el => el.setAttribute('tabindex', '-1'));
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search'), /skip home 390: next focus/);
        await broken.goto(base + '/');
        await broken.locator('main#main').evaluate(el => el.removeAttribute('tabindex'));
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search', 250), /skip home 390: main focus/);
        await broken.goto(base + '/');
        await broken.locator('.skip-link').evaluate(el => el.addEventListener('click', e => e.preventDefault()));
        await assert.rejects(checkSkipLink(broken, 'skip home 390', '#drug-search', 250), /skip home 390: fragment navigation/);
        await broken.close();
        const invalidLogin = await context.newPage();
        await invalidLogin.goto(base + '/staff/login/');
        await invalidLogin.locator('#id_username').fill('synthetic-invalid-user');
        await invalidLogin.locator('#id_password').fill('synthetic-invalid-password');
        const [invalidLoginResponse] = await Promise.all([
          invalidLogin.waitForNavigation({waitUntil: 'load'}),
          invalidLogin.locator('.staff-login-form button[type=submit]').click(),
        ]);
        assert.equal(invalidLoginResponse.status(), 200);
        assert.match(invalidLoginResponse.headers()['cache-control'], /no-store/);
        assert.equal(await invalidLogin.locator('.staff-alert-error').count(), 1);
        await checkSkipLink(invalidLogin, 'skip login 390', '#id_username');
        await invalidLogin.close();
      }
      await page.locator('#drug-search').fill('Browser Synthetic Product');
      await Promise.all([page.waitForURL('**/search/?q=Browser*'), page.keyboard.press('Enter')]);
      assert.equal(page.url().includes('/search/'), true);
      assert.equal(await page.locator('.result-card').count(), 1);
      assert.match(await page.locator('.result-card').innerText(), /داروی عمومی ساختگی مرورگر/);
      assert(!((await page.locator('body').innerText()).includes('ماده ساختگی خصوصی مرورگر')));
      await checkLayout(page, `search ${width}`);
      if (width === 390) await auditAccessibility(page, 'search results');
      await page.locator('.result-title-link').click();
      assert.match(page.url(), /\/products\/\d+\/$/);
      assert.match(await page.locator('h1').innerText(), /داروی عمومی ساختگی مرورگر/);
      await checkLayout(page, `product detail ${width}`);
      if (width === 390) await auditAccessibility(page, 'product detail');
      response = await page.goto(base + '/search/?q=synthetic%00canary');
      assert.equal(response.status(), 400);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.equal(response.headers()['referrer-policy'], 'no-referrer');
      assert.match(await page.locator('h1').innerText(), /عبارت جست‌وجو قابل پردازش نیست/);
      assert.equal(await page.locator('#drug-search').inputValue(), '');
      assert(!(await page.locator('body').innerText()).includes('synthetic'));
      await checkLayout(page, `invalid query ${width}`);
      if (width === 390) await auditAccessibility(page, 'invalid search query');
      await page.locator('#drug-search').fill('Browser Synthetic Product');
      await Promise.all([page.waitForURL('**/search/?q=Browser*'), page.locator('#drug-search').press('Enter')]);
      assert.equal(await page.locator('.result-card').count(), 1);
      const invalidCursorParams = new URLSearchParams({q: 'Browser Synthetic Product', cursor: 'cursor-canary-827<script>'});
      response = await page.goto(base + '/search/?' + invalidCursorParams);
      assert.equal(response.status(), 400);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.equal(response.headers()['referrer-policy'], 'no-referrer');
      assert.match(await page.locator('h1').innerText(), /ادامه جست‌وجو در دسترس نیست/);
      assert.equal(await page.locator('#drug-search').inputValue(), 'Browser Synthetic Product');
      assert(!(await page.locator('body').innerText()).includes('cursor-canary-827'));
      assert.equal(await page.locator('input[name=cursor]').count(), 0);
      await checkLayout(page, `invalid cursor ${width}`);
      if (width === 390) await auditAccessibility(page, 'invalid search cursor');
      await Promise.all([
        page.waitForURL(url => url.pathname === '/search/' && url.searchParams.get('q') === 'Browser Synthetic Product' && !url.searchParams.has('cursor')),
        page.locator('#drug-search').press('Enter'),
      ]);
      assert.equal(new URL(page.url()).searchParams.has('cursor'), false);
      assert.equal(await page.locator('.result-card').count(), 1);
      response = await page.goto(base + '/prices/');
      assert.equal(response.status(), 200);
      await checkLayout(page, `prices ${width}`);
      if (width === 390) await auditAccessibility(page, 'prices');
      response = await page.goto(base + '/about/');
      assert.equal(response.status(), 200);
      await checkLayout(page, `about ${width}`);
      await checkSkipLink(page, `skip about ${width}`, 'main .breadcrumbs a');
      if (width === 390) await auditAccessibility(page, 'about');
      response = await page.goto(base + `/staff/catalog/identity/ingredient/${ids.leaf}/lineage/`);
      assert.equal(response.status(), 200);
      assert(page.url().includes('/staff/login/'));
      assert.match(response.headers()['cache-control'], /no-store/);
      await checkSkipLink(page, `skip login ${width}`, '#id_username');
      if (width === 390) await auditAccessibility(page, 'login');
      await login(page, author);
      assert.equal(new URL(page.url()).pathname, '/staff/');
      assert.match(await page.locator('h1').innerText(), /فضای کاری همکاران/);
      assert.equal(await page.locator('a[href="/staff/catalog/identity/"]').count(), 1);
      assert.equal(await page.locator('a[href="/staff/prices/"]').count(), 0);
      await checkLayout(page, `staff workspace ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'staff workspace');
        await checkTextContrast(page, '.staff-alert', '.staff-alert', 'workspace warning');
        await checkTextContrast(page, '.staff-candidate .staff-detail-link', '.staff-candidate', 'workspace link');
      }
      await page.getByRole('link', {name: 'بدون بازبینی: نامزدهای فرآورده'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/products/');
      assert.equal(new URL(page.url()).search, '?status=pending');
      assert.equal(await page.locator('#status').inputValue(), 'pending');
      await page.getByRole('link', {name: 'فضای کاری همکاران ←'}).click();
      await page.getByRole('link', {name: 'ورود به ادعاهای منبع'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/sources/');
      assert.match(await page.locator('#date-summary-heading').innerText(), /خلاصه تاریخ در همین صفحه/);
      const summary = page.locator('section[aria-labelledby="date-summary-heading"]');
      assert.match(await summary.innerText(), /فقط 1 ادعای نمایش‌داده‌شده/);
      assert.match(await summary.locator('.staff-stat-grid > div').first().locator('span').innerText(), /گذشته/);
      assert.equal((await summary.locator('.staff-stat-grid > div').first().locator('strong').innerText()).trim(), '1');
      await page.goto(base + `/staff/sources/${ids.claim}/`);
      assert.match(await page.locator('.staff-review-item').filter({hasText: 'بازبینی منبع ساختگی برای مرورگر'}).innerText(), /بازبینی منبع ساختگی برای مرورگر/);
      assert.match(await page.locator('.staff-review-item').filter({hasText: 'browser-reviewer'}).innerText(), /browser-reviewer/);
      await checkLayout(page, `source review history ${width}`);
      if (width === 390) await auditAccessibility(page, 'source review history');
      await page.goto(base + `/staff/products/${ids.candidate}/`);
      assert.match(await page.locator('.staff-review-item').filter({hasText: 'بازبینی فرآورده ساختگی برای مرورگر'}).innerText(), /بازبینی فرآورده ساختگی برای مرورگر/);
      assert.match(await page.locator('.staff-review-item').filter({hasText: 'browser-reviewer'}).innerText(), /browser-reviewer/);
      assert.match(await page.locator('#comparison-heading').locator('..').innerText(), /وجود حساب ثبت‌کننده نامزدها در این مقایسه بررسی نمی‌شود/);
      await checkLayout(page, `product review history ${width}`);
      if (width === 390) await auditAccessibility(page, 'product review history');
      await page.goto(base + '/staff/sources/');
      await checkLayout(page, `source date summary ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'source date summary');
        await checkTextContrast(page, '#date-summary-heading', '.staff-section', 'summary heading');
        await checkTextContrast(page, '.staff-stat-grid > div:first-child span', '.staff-stat-grid > div', 'summary label');
        await checkTextContrast(page, '.staff-stat-grid > div:first-child strong', '.staff-stat-grid > div', 'summary count');
      }
      await page.getByRole('link', {name: 'پیمایش محدود تاریخ ادعاها ←'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/sources/dates/');
      assert.equal(await page.getByLabel('بعد از شناسه داخلی').count(), 1);
      assert.equal(await page.getByLabel('وضعیت تاریخ در این بخش').count(), 1);
      assert.match(await page.locator('main .staff-alert').innerText(), /وجود حساب ثبت‌کننده بررسی نمی‌شود/);
      await checkScanIdSyntax(page, `source scan ${width}`);
      await submitLocalizedScan(page, '۰۰۰۰');
      await checkStaffScanError(page, 'source scan', width);
      await page.getByRole('link', {name: 'فهرست ادعاهای منبع ←'}).focus();
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#after', `scan start ${width}`, '.staff-section');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#category', `scan category ${width}`, '.staff-section');
      if (width === 390) {
        const mutation = await page.addStyleTag({content: '#category:focus-visible { outline: none !important; }'});
        await assert.rejects(checkKeyboardFocus(page, '#category', 'mutated scan category', '.staff-section'), /missing focus outline/);
        await mutation.evaluate(node => node.remove());
      }
      await page.locator('#category').selectOption('expired');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '.staff-filter button', `scan submit ${width}`, '.staff-section');
      await Promise.all([page.waitForURL('**/staff/sources/dates/?after=0&category=expired'), page.keyboard.press('Enter')]);
      assert.equal(new URL(page.url()).searchParams.get('category'), 'expired');
      assert.match(await page.locator('main').innerText(), /بررسی‌شده در این بخش: 1/);
      assert.match(await page.locator('main').innerText(), /مطابق فیلتر در همین بخش: 1/);
      assert.equal(await page.getByRole('link', {name: 'جزئیات ادعا'}).count(), 1);
      await checkLayout(page, `source date scan ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'source date scan');
        await checkTextContrast(page, '.staff-alert', '.staff-alert', 'scan warning');
        await checkTextContrast(page, 'label[for="after"]', '.staff-section', 'scan start label');
        await checkTextContrast(page, '#after', '#after', 'scan start value');
        await checkTextContrast(page, 'label[for="category"]', '.staff-section', 'scan category label');
        await checkTextContrast(page, '#category', '#category', 'scan category selection');
        await checkTextContrast(page, '.staff-filter button', '.staff-filter button', 'scan submit text');
        await checkTextContrast(page, '.staff-candidate p', '.staff-candidate', 'scan result status');
        await checkTextContrast(page, '.staff-candidate .staff-detail-link', '.staff-candidate', 'scan result link');
        const mutation = await page.addStyleTag({content: '.staff-candidate p { color: #eee !important; }'});
        await assert.rejects(checkTextContrast(page, '.staff-candidate p', '.staff-candidate', 'mutated status'), /below 4.5:1/);
        await mutation.evaluate(node => node.remove());
        const backgroundMutation = await page.addStyleTag({content: '.staff-candidate { background-image: linear-gradient(white, black) !important; }'});
        await assert.rejects(checkTextContrast(page, '.staff-candidate p', '.staff-candidate', 'mutated background'), /background images/);
        await backgroundMutation.evaluate(node => node.remove());
      }
      await page.goto(base + '/staff/clinical/');
      await page.getByRole('link', {name: 'بازرسی فنی محدود پیش‌نویس‌ها ←'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/clinical/inspection/');
      assert.match(await page.locator('main .staff-alert').innerText(), /وجود حساب نویسنده بررسی نمی‌شود/);
      await checkScanIdSyntax(page, `clinical scan ${width}`);
      await submitLocalizedScan(page, '۰۰۰۰');
      await checkStaffScanError(page, 'clinical scan', width);
      await page.getByRole('link', {name: 'صف پیش‌نویس‌ها ←'}).focus();
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#after', `clinical scan start ${width}`, '.staff-section');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#category', `clinical scan category ${width}`, '.staff-section');
      await page.locator('#category').selectOption('available');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '.staff-filter button', `clinical scan submit ${width}`, '.staff-section');
      await Promise.all([page.waitForURL('**/staff/clinical/inspection/?after=0&category=available'), page.keyboard.press('Enter')]);
      assert.match(await page.locator('main').innerText(), /بررسی‌شده در این بخش: 22/);
      assert.equal(await page.getByRole('link', {name: 'جزئیات پیش‌نویس'}).count(), 22);
      assert(!(await page.locator('main').innerText()).includes('عنوان خصوصی مرورگر'));
      await checkLayout(page, `clinical scan ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'clinical scan');
        await checkTextContrast(page, '.staff-candidate p', '.staff-candidate', 'clinical scan status');
      }
      await page.goto(base + `/staff/clinical/${ids.clinical_leaf}/`);
      const clinicalDetail = page.locator('main');
      assert.match(await clinicalDetail.innerText(), /اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند/);
      assert.match(await clinicalDetail.innerText(), /شناسه ارجاع‌های ثبت‌شده با فهرست فعلی برابر است/);
      assert.match(await clinicalDetail.innerText(), /خوانش‌های جداگانه‌اند، زمان تغییر را ثابت نمی‌کنند/);
      await checkLayout(page, `clinical review detail ${width}`);
      if (width === 390) await auditAccessibility(page, 'clinical review detail');
      await page.getByRole('link', {name: 'بازرسی فنی تاریخچه بازبینی‌ها ←'}).click();
      const reviewInspection = `/staff/clinical/${ids.clinical_leaf}/reviews/inspection/`;
      assert.equal(new URL(page.url()).pathname, reviewInspection);
      await checkScanIdSyntax(page, `clinical review scan ${width}`);
      await submitLocalizedScan(page, '۰۰۰۰');
      await checkStaffScanError(page, 'clinical review scan', width);
      await page.getByRole('link', {name: 'بازگشت به پیش‌نویس ←'}).focus();
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#after', `review scan start ${width}`, '.staff-section');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#category', `review scan category ${width}`, '.staff-section');
      await page.locator('#category').selectOption('consistent');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '.staff-filter button', `review scan submit ${width}`, '.staff-section');
      await Promise.all([page.waitForURL('**/reviews/inspection/?after=0&category=consistent'), page.keyboard.press('Enter')]);
      assert.match(await page.locator('main').innerText(), /بررسی‌شده در این بخش: 1/);
      assert.equal(await page.locator('.staff-candidate').count(), 1);
      assert(!(await page.locator('main').innerText()).includes('دلیل خصوصی ساختگی بازبینی مرورگر'));
      await checkLayout(page, `clinical review scan ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'clinical review scan');
        await checkTextContrast(page, '.staff-candidate p', '.staff-candidate', 'clinical review scan status');
      }
      await page.goto(base + `/staff/clinical/${ids.clinical_leaf}/`);
      await page.getByRole('link', {name: 'بازرسی مسیر نسخه‌های پیشین ←'}).click();
      const clinicalLineage = `/staff/clinical/${ids.clinical_leaf}/lineage/`;
      assert.equal(new URL(page.url()).pathname, clinicalLineage);
      assert.equal(await page.locator('.staff-panel').count(), 20);
      assert(!(await page.locator('main').innerText()).includes('نسخه خصوصی مرورگر'));
      await checkLayout(page, `clinical lineage ${width}`);
      if (width === 390) await auditAccessibility(page, 'clinical lineage');
      await page.getByRole('link', {name: 'بررسی بخش بعدی ←'}).focus();
      await Promise.all([page.waitForURL('**/lineage/?cursor=*'), page.keyboard.press('Enter')]);
      assert.equal(await page.locator('.staff-panel').count(), 1);
      assert.match(await page.locator('main').innerText(), /گام 21/);
      assert.match(await page.locator('main').innerText(), /والدی ثبت نشده/);
      const lineageParams = new URLSearchParams({cursor: 'clinical-canary<script>'});
      response = await page.goto(base + clinicalLineage + '?' + lineageParams);
      assert.equal(response.status(), 400);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.equal(response.headers()['referrer-policy'], 'same-origin');
      assert(!(await page.locator('body').innerText()).includes('clinical-canary'));
      await checkLayout(page, `clinical lineage error ${width}`);
      if (width === 390) await auditAccessibility(page, 'clinical lineage error');
      const restartLineage = page.getByRole('link', {name: 'شروع دوباره بازرسی ←'});
      assert.equal(await restartLineage.getAttribute('href'), clinicalLineage);
      await restartLineage.focus();
      await Promise.all([page.waitForURL(url => url.pathname === clinicalLineage && url.search === ''), page.keyboard.press('Enter')]);
      assert.equal(await page.locator('.staff-panel').count(), 20);
      await page.goto(base + '/staff/sources/dates/');
      await page.getByRole('link', {name: 'فضای کاری همکاران ←'}).click();
      await page.getByRole('link', {name: 'ورود به بازرسی کاتالوگ'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/catalog/quality/');
      assert.equal(await page.getByLabel('بعد از شناسه داخلی').count(), 1);
      await checkScanIdSyntax(page, `catalog scan ${width}`);
      await submitLocalizedScan(page, '٠٠٠٠');
      await checkStaffScanError(page, 'catalog scan', width);
      await page.getByRole('link', {name: 'صف نامزدهای فرآورده ←'}).focus();
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '#after', `quality start ${width}`, '.staff-section');
      await page.keyboard.press('Tab');
      await checkKeyboardFocus(page, '.staff-filter button', `quality submit ${width}`, '.staff-section');
      await Promise.all([page.waitForURL('**/staff/catalog/quality/?after=0'), page.keyboard.press('Enter')]);
      assert.match(await page.locator('main').innerText(), /بررسی‌شده در این بخش: 1/);
      await checkLayout(page, `catalog quality ${width}`);
      if (width === 390) {
        await auditAccessibility(page, 'catalog quality');
        await checkTextContrast(page, '#after', '#after', 'quality start value');
      }
      await page.getByRole('link', {name: 'فضای کاری همکاران ←'}).click();
      await page.getByRole('link', {name: 'ورود به هویت ساختگی کاتالوگ'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/catalog/identity/');
      await page.getByRole('link', {name: 'فضای کاری همکاران ←'}).click();
      assert.equal(new URL(page.url()).pathname, '/staff/');
      response = await page.goto(base + `/staff/catalog/identity/formulation/${ids.formulation}/correction/`);
      assert.equal(response.status(), 200);
      await checkLayout(page, `identity form ${width}`);
      if (width === 390) await auditAccessibility(page, 'identity form');
      response = await page.goto(base + `/staff/catalog/identity/package/${ids.package}/`);
      assert.equal(response.status(), 200);
      assert.match(await page.locator('main').innerText(), /نمایش و بازرسی پیوندها آن را کنترل نمی‌کنند/);
      assert.match(await page.locator('main').innerText(), /وجود فعلی حساب بازبین، هویت تاریخی یا صلاحیت او را اثبات نمی‌کند/);
      assert.match(await page.locator('main').innerText(), /آخرین بازبینی موجود نیز قفل می‌شود/);
      assert.match(await page.locator('main').innerText(), /این قفل مانع همه درج‌های جدید یا تغییر پس از تراکنش نیست/);
      await checkLayout(page, `identity package detail ${width}`);
      if (width === 390) await auditAccessibility(page, 'identity package detail');
      response = await page.goto(base + `/staff/catalog/identity/ingredient/${ids.leaf}/lineage/`);
      assert.equal(response.status(), 200);
      assert.match(await page.locator('main').innerText(), /وجود حساب ثبت‌کنندگان زنجیره و پیوندهای اصلاح در این بررسی کنترل نمی‌شود/);
      assert.match(response.headers()['x-robots-tag'], /noindex/);
      await checkLayout(page, `lineage ${width}`);
      if (width === 390) await auditAccessibility(page, 'lineage');
      await page.getByRole('link', {name: 'بررسی بخش بعدی'}).click();
      assert.match(await page.locator('body').innerText(), /گام ۲۱|گام 21/);
      await checkLayout(page, `lineage next ${width}`);
      response = await page.goto(base + `/staff/operations/imports/${ids.receipt}/inspection/?after=bad-canary`);
      assert.equal(response.status(), 404, 'a product-only viewer cannot inspect price receipts');
      await context.close();
      const priceContext = await contextFor(browser, width, errors);
      const pricePage = await priceContext.newPage();
      await login(pricePage, 'browser-price-stager');
      response = await pricePage.goto(base + '/staff/prices/import/');
      assert.equal(response.status(), 200);
      assert.match(await pricePage.locator('.staff-panel-note').innerText(), /اولین نتیجه تطبیق/);
      await checkLayout(pricePage, `price preview form ${width}`);
      if (width === 390) await auditAccessibility(pricePage, 'price preview form');
      await pricePage.locator('#id_source_name').fill('منبع ساختگی مرورگر');
      await pricePage.locator('#id_source_url').fill('https://example.org/browser-price');
      const csv = 'source_record_id,irc,manufacturer,strength,dosage_form,package_description,amount,currency,category,unit,effective_date,source_published_date\n' +
        'browser-1,001,سازنده فرضی,1 mg,قرص,10 عدد,100,RIAL,retail,package,,\n' +
        'browser-2,۰۰۱,سازنده فرضی,1 mg,قرص,10 عدد,200,RIAL,retail,package,,\n' +
        'browser-3,001,سازنده فرضی,2 mg,قرص,10 عدد,300,RIAL,retail,package,,\n';
      await pricePage.locator('#id_csv_file').setInputFiles({name: 'synthetic-'.repeat(15) + '.csv', mimeType: 'text/csv', buffer: Buffer.from(csv)});
      await checkLayout(pricePage, `price preview with selected file ${width}`);
      let stylesheetRequests = 0;
      if (width === 320) {
        // Exercise a slow stylesheet on the POST response; main-document response
        // alone does not mean layout styles have loaded.
        await pricePage.route('**/static/css/staff.css', async route => {
          stylesheetRequests++;
          await new Promise(resolve => setTimeout(resolve, 250));
          await route.continue();
        });
      }
      const [preview] = await Promise.all([
        pricePage.waitForResponse(r => r.url().endsWith('/staff/prices/import/') && r.request().method() === 'POST'),
        pricePage.locator('.staff-review-form button[type=submit]').click(),
      ]);
      assert.equal(preview.status(), 200);
      await pricePage.waitForLoadState('load');
      if (width === 320) {
        assert(stylesheetRequests > 0, 'slow stylesheet probe was not requested');
        await pricePage.unroute('**/static/css/staff.css');
      }
      assert.equal(await pricePage.locator('.staff-review-form').evaluate(el => getComputedStyle(el).display), 'grid',
                   'price result stylesheet must be loaded');
      assert.match(await pricePage.locator('.staff-upload-result').innerText(), /ردیف‌ها: 3/);
      assert.match(await pricePage.locator('.staff-upload-result').innerText(), /پیشنهاد تطبیق: 2/);
      assert.match(await pricePage.locator('.staff-upload-result').innerText(), /بدون تطبیق: 1/);
      assert.match(await pricePage.locator('.staff-upload-result').innerText(), /هیچ قیمتی منتشر نشده/);
      await checkLayout(pricePage, `price preview result ${width}`);
      response = await pricePage.goto(base + `/staff/prices/${ids.price}/`);
      assert.equal(response.status(), 200);
      assert.equal(await pricePage.getByText('این بازبینی تضمین یکتایی نیست', {exact: false}).count(), 1);
      assert.match(await pricePage.locator('.staff-review-item').filter({hasText: 'بازبینی قیمت ساختگی برای مرورگر'}).innerText(), /بازبینی قیمت ساختگی برای مرورگر/);
      assert.match(await pricePage.locator('.staff-review-item').filter({hasText: 'browser-reviewer'}).innerText(), /browser-reviewer/);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.match(await pricePage.locator('#price-comparison-heading').locator('..').innerText(), /وجود حساب ثبت‌کننده نامزدها در این مقایسه بررسی نمی‌شود/);
      await checkLayout(pricePage, `price detail ${width}`);
      if (width === 390) await auditAccessibility(pricePage, 'price detail');
      assert.match(await pricePage.locator('main').innerText(), /حساب ثبت‌کننده رسید در این فهرست بررسی نمی‌شود/);
      response = await pricePage.goto(base + '/staff/operations/imports/');
      assert.equal(response.status(), 200);
      assert.match(await pricePage.locator('main').innerText(), /نمایش نام حساب فعلی، هویت تاریخی یا صلاحیت را اثبات نمی‌کند/);
      await checkLayout(pricePage, `receipt list ${width}`);
      response = await pricePage.goto(base + `/staff/operations/imports/${ids.receipt}/`);
      assert.equal(response.status(), 200);
      assert.match(await pricePage.locator('main').innerText(), /نمایش نام حساب فعلی، هویت تاریخی یا صلاحیت را اثبات نمی‌کند/);
      assert.match(response.headers()['cache-control'], /no-store/);
      await checkLayout(pricePage, `receipt detail ${width}`);
      if (width === 390) await auditAccessibility(pricePage, 'receipt detail');
      const receiptInspection = `/staff/operations/imports/${ids.receipt}/inspection/`;
      response = await pricePage.goto(base + receiptInspection);
      assert.equal(response.status(), 200);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.match(await pricePage.locator('main').innerText(), /ردیف داده 1/);
      assert.match(await pricePage.locator('main').innerText(), /ردیف داده 2/);
      assert(!(await pricePage.locator('main').innerText()).includes('browser-detail'));
      assert.match(await pricePage.locator('main').innerText(), /حساب ثبت‌کننده رسید در این بازرسی بررسی نمی‌شود/);
      await checkLayout(pricePage, `receipt inspection ${width}`);
      if (width === 390) await auditAccessibility(pricePage, 'receipt inspection');
      await pricePage.locator('#after').fill('۵۰۰۱');
      const [invalidScan] = await Promise.all([
        pricePage.waitForResponse(r => r.url().includes(receiptInspection) && r.request().method() === 'GET'),
        pricePage.locator('.staff-filter button').click(),
      ]);
      assert.equal(invalidScan.status(), 400);
      await pricePage.waitForLoadState('load');
      assert.match(invalidScan.headers()['cache-control'], /no-store/);
      assert(!(await pricePage.locator('main').innerText()).includes('۵۰۰۱'));
      await checkLayout(pricePage, `receipt inspection error ${width}`);
      await pricePage.getByRole('link', {name: 'شروع دوباره بازرسی ←'}).click();
      assert.equal(new URL(pricePage.url()).pathname, receiptInspection);
      await priceContext.close();
    }
    // A malformed hidden review version gets a private 400 and a safe GET
    // recovery link, rather than requiring the user to resubmit the bad form.
    const reviewContext = await contextFor(browser, 390, errors);
    const reviewPage = await reviewContext.newPage();
    await login(reviewPage, reviewer);
    for (const [detailPath, domain] of [[`/staff/sources/${ids.claim}/`, 'source'],
                                        [`/staff/clinical/${ids.clinical_leaf}/`, 'clinical']]) {
      let response = await reviewPage.goto(base + detailPath);
      assert.equal(response.status(), 200);
      const form = reviewPage.locator('form.staff-review-form');
      const oldVersion = await form.locator('#id_expected_review').inputValue();
      await form.locator('#id_decision').selectOption('defer');
      await form.locator('#id_reason').fill('بازبینی ساختگی برای آزمایش خطا');
      await form.locator('#id_expected_review').evaluate(el => { el.value = '9223372036854775808'; });
      [response] = await Promise.all([reviewPage.waitForNavigation({waitUntil: 'load'}),
                                     form.locator('button[type=submit]').click()]);
      assert.equal(response.status(), 400);
      assert.match(response.headers()['cache-control'], /no-store/);
      assert.match(response.headers()['x-robots-tag'], /noindex/);
      assert.equal(response.headers()['referrer-policy'], 'same-origin');
      const alert = reviewPage.getByRole('alert').filter({hasText: 'شناسه بازبینی معتبر نیست'});
      assert.equal(await alert.count(), 1);
      const retry = alert.getByRole('link', {name: 'بازگشت به جزئیات و شروع دوباره ←'});
      assert.equal(await retry.getAttribute('href'), detailPath);
      await checkLayout(reviewPage, `${domain} invalid review 390`);
      await auditAccessibility(reviewPage, `${domain} invalid review`);
      await Promise.all([reviewPage.waitForURL(base + detailPath), retry.click()]);
      assert.equal(await reviewPage.locator('form.staff-review-form #id_expected_review').inputValue(), oldVersion);
      assert.equal(await reviewPage.locator('form.staff-review-form #id_reason').inputValue(), '');
      assert.equal(await reviewPage.locator('form.staff-review-form #id_decision').inputValue(), '');
    }
    await reviewContext.close();
    const authorContext = await contextFor(browser, 390, errors);
    const page = await authorContext.newPage();
    await login(page, author);
    // A valid session must still be unable to submit a POST without a CSRF token.
    const rejected = await page.evaluate(async () => (await fetch('/staff/catalog/identity/new/ingredient/', {
      method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: 'name_fa=csrf-canary',
    })).status);
    assert.equal(rejected, 403, 'missing CSRF token must be rejected');
    await page.goto(base + '/staff/catalog/identity/new/ingredient/');
    await page.locator('#id_source_name').fill('   ');
    await page.locator('#id_source_url').fill('https://example.org/fixture');
    await page.locator('#id_name_fa').fill('ماده تازه ساختگی مرورگر');
    await page.locator('#id_synthetic_ack').check();
    const [invalid] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith('/identity/new/ingredient/') && r.request().method() === 'POST'),
      page.locator('form.staff-review-form button[type=submit]').click(),
    ]);
    assert.equal(invalid.status(), 200);
    const sourceField = page.locator('#id_source_name');
    assert.equal(await sourceField.getAttribute('aria-invalid'), 'true');
    const describedBy = await sourceField.getAttribute('aria-describedby');
    assert(describedBy && describedBy.split(/\s+/).includes('id_source_name_error'));
    assert((await page.locator('#id_source_name_error').innerText()).trim());
    await auditAccessibility(page, 'invalid identity form');
    await sourceField.fill('منبع ساختگی');
    await Promise.all([page.waitForURL(/\/staff\/catalog\/identity\/ingredient\/\d+\/$/),
      page.locator('form.staff-review-form button[type=submit]').click()]);
    assert.match(await page.locator('body').innerText(), /ماده تازه ساختگی مرورگر/);
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
    await auditAccessibility(second, 'stale review');
    // An actual cross-origin navigation is intercepted before it leaves the test;
    // same-origin policy must not send the private staff URL to the destination.
    await first.evaluate(() => { const a = document.createElement('a'); a.href = 'https://example.org/privacy-test'; a.id = 'external-test'; a.textContent = 'External synthetic link'; document.body.append(a); });
    const [external] = await Promise.all([first.waitForRequest('https://example.org/privacy-test'), first.locator('#external-test').click()]);
    assert.equal(external.headers()['referer'], undefined);
    await page.goto(base + '/staff/catalog/identity/');
    await Promise.all([page.waitForURL(base + '/'), page.locator('form[action="/staff/logout/"] button').click()]);
    const afterLogout = await page.goto(base + `/staff/catalog/identity/ingredient/${ids.ingredient}/`);
    assert.equal(afterLogout.status(), 200);
    assert(page.url().includes('/staff/login/'), 'logout must remove access to private pages');
    await firstContext.close(); await secondContext.close(); await authorContext.close();
    // Emulation checks the selected controls, not actual OS/device support.
    const accessibleContext = await contextFor(browser, 390, errors,
      {forcedColors: 'active', reducedMotion: 'reduce'});
    const accessiblePage = await accessibleContext.newPage();
    await accessiblePage.goto(base + '/');
    assert(await accessiblePage.evaluate(() => matchMedia('(forced-colors: active)').matches &&
      matchMedia('(prefers-reduced-motion: reduce)').matches));
    assert.equal(await accessiblePage.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), 'auto');
    await checkSkipLink(accessiblePage, 'skip forced-home 390', '#drug-search');
    await checkKeyboardFocus(accessiblePage, '#drug-search', 'forced-colors search', '.search-form');
    await accessiblePage.locator('#drug-search').fill('Browser Synthetic Product');
    await Promise.all([accessiblePage.waitForURL('**/search/?q=Browser*'), accessiblePage.keyboard.press('Enter')]);
    assert.equal(await accessiblePage.locator('.result-card').count(), 1);
    await checkLayout(accessiblePage, 'forced-colors search results');
    await accessiblePage.goto(base + '/staff/login/');
    await checkSkipLink(accessiblePage, 'skip forced-login 390', '#id_username');
    await login(accessiblePage, author);
    await accessiblePage.goto(base + '/staff/sources/dates/');
    await accessiblePage.getByRole('link', {name: 'فهرست ادعاهای منبع ←'}).focus();
    await accessiblePage.keyboard.press('Tab');
    await checkKeyboardFocus(accessiblePage, '#after', 'forced-colors scan start', '.staff-section');
    await accessiblePage.keyboard.press('Tab');
    await checkKeyboardFocus(accessiblePage, '#category', 'forced-colors scan category', '.staff-section');
    await accessiblePage.locator('#category').selectOption('expired');
    await accessiblePage.keyboard.press('Tab');
    await checkKeyboardFocus(accessiblePage, '.staff-filter button', 'forced-colors scan submit', '.staff-section');
    await Promise.all([accessiblePage.waitForURL('**/staff/sources/dates/?after=0&category=expired'), accessiblePage.keyboard.press('Enter')]);
    assert.equal(await accessiblePage.getByRole('link', {name: 'جزئیات ادعا'}).count(), 1);
    await checkLayout(accessiblePage, 'forced-colors source date scan');
    await accessiblePage.goto(base + '/staff/catalog/identity/new/ingredient/');
    await accessiblePage.locator('#id_source_name').focus();
    await accessiblePage.keyboard.press('Tab');
    await checkKeyboardFocus(accessiblePage, '#id_source_url', 'forced-colors source URL', '.staff-panel');
    await accessiblePage.keyboard.press('Tab');
    await checkKeyboardFocus(accessiblePage, '#id_synthetic_ack', 'forced-colors acknowledgment', '.staff-panel');
    await accessiblePage.keyboard.press('Space');
    assert(await accessiblePage.locator('#id_synthetic_ack').isChecked());
    await accessiblePage.keyboard.press('Space');
    assert(!(await accessiblePage.locator('#id_synthetic_ack').isChecked()));
    await accessibleContext.close();
    assert.deepEqual(errors, [], 'browser JavaScript errors');
    console.log(`browser checks passed (Chromium ${browser.version()}, widths 320/390/768/1440)`);
  } finally {
    if (browser) await browser.close();
    fs.rmSync(temp, {recursive: true, force: true});
  }
}
run().catch(error => { console.error(error.stack || String(error)); process.exitCode = 1; });
