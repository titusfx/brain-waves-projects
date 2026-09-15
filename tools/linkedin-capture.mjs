#!/usr/bin/env node
/**
 * linkedin-capture.mjs — produce LinkedIn-ready assets from the running workbench.
 *
 * Why this exists: the post claims a live instrument, so the post needs to *show* one. Doing
 * that by hand means a screen recorder, a steady hand and a re-shoot every time the UI
 * changes. This drives the app the same way `tools/verify-web.mjs` does — headless Chrome
 * over the DevTools protocol — and always produces the same tour.
 *
 * No dependencies, on purpose: `verify-web.mjs` already proves raw CDP is enough, and a
 * Playwright install would be several hundred megabytes, a browser download and a second
 * browser version to keep in step, to do what forty lines of WebSocket already do here.
 *
 *   node tools/linkedin-capture.mjs                # stills + carousel slides + video
 *   node tools/linkedin-capture.mjs --stills       # screenshots and carousel slides only
 *   node tools/linkedin-capture.mjs --video        # the demo video only
 *   node tools/linkedin-capture.mjs --keep-dataset # leave the synthetic datasets behind
 *
 * The API must be serving the built app (it is the same origin the video is recorded from):
 *
 *   npm run build:web
 *   npm run api:prod
 *   npm run linkedin
 *
 * Everything it records is the **synthetic** source. It is labelled `demo` in the app for
 * exactly the reason this file insists on it: a demo that could be mistaken for a head would
 * be a hazard rather than a feature, and a LinkedIn post is where that mistake gets made.
 */
import { spawn, spawnSync } from 'node:child_process';
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

// --------------------------------------------------------------------------- config
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8020';
const OUT = resolve(process.env.OUT_DIR ?? join('linkedin', 'out'));
const STILLS_DIR = join(OUT, 'stills');
const CAROUSEL_DIR = join(OUT, 'carousel');
const VIDEO_DIR = join(OUT, 'video');
const PDF_CHECK_DIR = join(OUT, 'pdf-check');
const FRAMES_DIR = join(VIDEO_DIR, 'frames');
/**
 * README assets live outside `out/` because they are **committed**, not build output — a README
 * image has to exist in the repository for GitHub to render it.
 */
const DOCS_DIR = resolve('docs');
const DOCS_IMAGES_DIR = join(DOCS_DIR, 'images');
const HERO_HTML = resolve('docs', 'hero.html');
const SLIDES_HTML = resolve('linkedin', 'slides.html');
/** Document posts ask for a title; this also becomes the PDF's own Title metadata. */
const PDF_TITLE =
  process.env.PDF_TITLE ?? 'Raw EEG, no licence: reverse-engineering the EPOC+';
/** The mixed deck (text + app screenshots) that becomes the uploadable carousel PDF. */
const CAROUSEL_HTML = resolve('linkedin', 'carousel.html');
/** Screenshots the carousel HTML embeds. Checked before printing so a PDF never ships a gap. */
const CAROUSEL_SHOTS = [
  '01-monitor',
  '03-protocols',
  '04-run-countdown',
  '06-run-finished',
  '08-dataset-states',
  '09-discovery',
];

const CDP_PORT = Number(process.env.CDP_PORT ?? 9334);
const STILL_SIZE = parseSize(process.env.STILL_SIZE ?? '1200x1500');
const VIDEO_SIZE = parseSize(process.env.VIDEO_SIZE ?? '1080x1350');
const SLIDE_SIZE = parseSize(process.env.SLIDE_SIZE ?? '1080x1350');
const HERO_SIZE = parseSize(process.env.HERO_SIZE ?? '1280x640');

/** The synthetic dataset the Datasets and Discovery screenshots need in order to exist. */
const DATASET_NAME = process.env.DATASET_NAME ?? 'showcase eyes closed vs open';

const FLAGS = new Set(process.argv.slice(2));
// Naming a mode flag switches to "only that mode"; naming none means all of them. Without this,
// `--pdf` would also re-record a two-minute video nobody asked for.
const MODES = ['--stills', '--video', '--pdf', '--readme'].filter((flag) => FLAGS.has(flag));
const WANT_STILLS = MODES.length === 0 || MODES.includes('--stills');
const WANT_VIDEO = MODES.length === 0 || MODES.includes('--video');
const WANT_PDF = MODES.length === 0 || MODES.includes('--pdf');
const WANT_README = MODES.length === 0 || MODES.includes('--readme');
const KEEP_DATASET = FLAGS.has('--keep-dataset');
const VIDEO_QUALITY = Number(process.env.VIDEO_QUALITY ?? 90);

if (FLAGS.has('--help') || FLAGS.has('-h')) {
  console.log(
    [
      'usage: node tools/linkedin-capture.mjs [--stills] [--video] [--pdf] [--readme]',
      '                                      [--keep-dataset]',
      '',
      '  no mode flag   everything below',
      '  --stills       app screenshots and the per-slide PNGs',
      '  --video        the demo video only',
      '  --pdf          the uploadable carousel PDF (needs the stills to exist)',
      '  --readme       committed README assets in docs/ (needs the stills to exist)',
      '',
      'env: BASE_URL OUT_DIR CDP_PORT CHROME_PATH FFMPEG_PATH',
      '     STILL_SIZE VIDEO_SIZE SLIDE_SIZE HERO_SIZE VIDEO_QUALITY DATASET_NAME',
    ].join('\n'),
  );
  process.exit(0);
}

function parseSize(value) {
  const match = /^(\d+)x(\d+)$/.exec(String(value).trim());
  if (!match) throw new Error(`not a WxH size: ${value}`);
  // Both dimensions must be even: H.264 with yuv420p cannot encode an odd width or height.
  const width = Number(match[1]) - (Number(match[1]) % 2);
  const height = Number(match[2]) - (Number(match[2]) % 2);
  return { width, height };
}

const CHROME =
  process.env.CHROME_PATH ??
  [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].find((path) => existsSync(path));

const FFMPEG =
  process.env.FFMPEG_PATH ?? (spawnSync('ffmpeg', ['-version'], { stdio: 'ignore' }).error ? null : 'ffmpeg');

if (!CHROME) {
  console.error('no Chrome found; set CHROME_PATH');
  process.exit(2);
}

const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
const log = (message) => console.log(message);

/** Dataset directories this run created, removed again on the way out unless asked. */
const created = [];
let cdp;
let chrome;

// --------------------------------------------------------------------------- CDP
class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve: done, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else done(message.result);
        return;
      }
      for (const handler of this.listeners.get(message.method) ?? []) handler(message.params);
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((done, reject) => this.pending.set(id, { resolve: done, reject }));
  }

  on(method, handler) {
    const list = this.listeners.get(method) ?? [];
    list.push(handler);
    this.listeners.set(method, list);
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? 'evaluate failed');
    }
    return result.result.value;
  }

  async waitFor(expression, { timeout = 15000, label = expression } = {}) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await this.evaluate(`Boolean(${expression})`)) return true;
      await sleep(150);
    }
    throw new Error(`timed out waiting for ${label}`);
  }

  async goto(url) {
    const loaded = new Promise((done) => {
      const once = (params) => {
        void params;
        this.listeners.set(
          'Page.loadEventFired',
          (this.listeners.get('Page.loadEventFired') ?? []).filter((fn) => fn !== once),
        );
        done();
      };
      this.on('Page.loadEventFired', once);
    });
    await this.send('Page.navigate', { url });
    await loaded;
    // A navigation throws away everything injected into the page, cursor included. Without
    // this the video loses its pointer after the first scene and every later interaction
    // looks like it happened by itself.
    if (this.cursorWanted) await this.enableCursor();
  }

  /** Screenshot the viewport. */
  async shot(name, directory = STILLS_DIR) {
    const { data } = await this.send('Page.captureScreenshot', { format: 'png' });
    const path = join(directory, `${name}.png`);
    writeFileSync(path, Buffer.from(data, 'base64'));
    return path;
  }

  /**
   * Screenshot one element by its page-absolute box.
   *
   * `captureBeyondViewport` is what makes this work on a page taller than the window: the clip
   * is in page coordinates, not viewport coordinates, so the carousel slides can be cut out of
   * one long document without scrolling and hoping the scroll landed on the boundary.
   */
  async shotElement(selector, name, directory = CAROUSEL_DIR) {
    const box = await this.evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {
        x: rect.left + window.scrollX,
        y: rect.top + window.scrollY,
        width: rect.width,
        height: rect.height,
      };
    })()`);
    if (!box) throw new Error(`${selector} is not on the page`);
    const { data } = await this.send('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: true,
      clip: { x: box.x, y: box.y, width: box.width, height: box.height, scale: 1 },
    });
    const path = join(directory, `${name}.png`);
    writeFileSync(path, Buffer.from(data, 'base64'));
    return path;
  }

  async dump(name, directory = STILLS_DIR) {
    const text = await this.evaluate('document.body.innerText');
    writeFileSync(join(directory, `${name}.txt`), `${text}\n`);
    return text;
  }

  // ------------------------------------------------------------------ overlays
  /**
   * A full-bleed title card over whatever is on screen.
   *
   * It is an overlay rather than a separate page because `Page.navigate` would destroy it:
   * the card has to survive a moment past the navigation that follows it, and over a blurred
   * live monitor reads better than a black frame anyway.
   */
  async showCard(title, subtitle) {
    await this.evaluate(`(() => {
      document.getElementById('__lp_card')?.remove();
      const card = document.createElement('div');
      card.id = '__lp_card';
      card.style.cssText = [
        'position:fixed', 'inset:0', 'z-index:2147483646',
        'display:flex', 'flex-direction:column', 'justify-content:center',
        'gap:42px', 'padding:96px',
        'background:rgba(2,6,23,.965)',
        'font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif',
        'color:#f1f5f9', 'text-align:left',
      ].join(';');
      const heading = document.createElement('div');
      heading.textContent = ${JSON.stringify(title)};
      heading.style.cssText = 'font-size:78px;font-weight:800;line-height:1.12;letter-spacing:-.02em';
      const sub = document.createElement('div');
      sub.textContent = ${JSON.stringify(subtitle)};
      sub.style.cssText = 'font-size:42px;line-height:1.45;color:#94a3b8;font-weight:500;white-space:pre-line';
      card.append(heading, sub);
      document.body.appendChild(card);
    })()`);
  }

  async hideCard() {
    await this.evaluate(`document.getElementById('__lp_card')?.remove()`);
  }

  // ----------------------------------------------------------------- screencast
  async startRecording({ width, height, quality }) {
    rmSync(FRAMES_DIR, { recursive: true, force: true });
    mkdirSync(FRAMES_DIR, { recursive: true });
    this.frames = [];
    const started = Date.now();
    this.on('Page.screencastFrame', ({ data, sessionId, metadata }) => {
      const index = this.frames.length;
      writeFileSync(join(FRAMES_DIR, `f${String(index).padStart(5, '0')}.jpg`), Buffer.from(data, 'base64'));
      // Chrome's timestamp is seconds on a monotonic clock; wall time is the safer of the two
      // to difference, and frame pacing is all this needs.
      this.frames.push({ index, at: metadata?.timestamp ? metadata.timestamp * 1000 : Date.now() - started });
      // Acking is mandatory: without it Chrome sends one frame and stops.
      this.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
    });
    await this.send('Page.startScreencast', {
      format: 'jpeg',
      quality,
      maxWidth: width,
      maxHeight: height,
      everyNthFrame: 1,
    });
  }

  async stopRecording() {
    await this.send('Page.stopScreencast');
    await sleep(400); // let the last frame land and be written
    return this.frames ?? [];
  }

  /** A visible fake pointer, so the video shows what is being interacted with. */
  async enableCursor() {
    this.cursorWanted = true;
    await this.evaluate(`(() => {
      if (document.getElementById('__lp_cursor')) return;
      const dot = document.createElement('div');
      dot.id = '__lp_cursor';
      dot.style.cssText = [
        'position:fixed', 'left:-200px', 'top:-200px', 'z-index:2147483647',
        'width:22px', 'height:22px', 'margin:-11px 0 0 -11px', 'border-radius:9999px',
        'background:rgba(16,185,129,.95)',
        'box-shadow:0 0 0 3px rgba(255,255,255,.92),0 3px 14px rgba(0,0,0,.6)',
        'pointer-events:none', 'transition:left 110ms linear,top 110ms linear',
      ].join(';');
      document.body.appendChild(dot);
    })()`);
  }
}

async function openTarget() {
  const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?about:blank`, { method: 'PUT' });
  const target = await response.json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((done, reject) => {
    socket.addEventListener('open', done, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  const instance = new Cdp(socket);
  await instance.send('Page.enable');
  await instance.send('Runtime.enable');
  await instance.send('Log.enable');
  return instance;
}

// --------------------------------------------------------------------------- API
async function api(path, options) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'content-type': 'application/json' },
    ...options,
  });
  const text = await response.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  return { status: response.status, body };
}

/**
 * Insist on the synthetic source.
 *
 * Every asset this file produces must be a labelled demo. If the dongle happens to be streaming
 * a real head, a screenshot of it would be a real person's brain data — which must never be
 * published — so this is about privacy as much as about honesty.
 */
async function ensureDemo() {
  const status = await api('/api/system/status');
  if (status.body?.source !== 'demo') {
    const switched = await api('/api/system/source', {
      method: 'POST',
      body: JSON.stringify({ mode: 'demo' }),
    });
    if (switched.body?.source !== 'demo') {
      throw new Error(
        `could not switch to the demo source (got ${switched.body?.source}); ` +
          'refusing to record — a public post must not contain a real head',
      );
    }
  }
  for (let i = 0; i < 80; i += 1) {
    const now = await api('/api/system/status');
    if ((now.body?.stats?.samples ?? 0) > 256) {
      return { samples: now.body.stats.samples };
    }
    await sleep(150);
  }
  throw new Error('the demo source produced no samples');
}

/** A finished two-state dataset, so Datasets and Discovery have something real to show. */
async function buildShowcaseDataset() {
  // Start the synthetic source FIRST, before any early return. Reusing an existing dataset
  // used to skip this, and the Run scene then failed with "nothing is streaming" — because the
  // previous run had left the source idle. The source is a precondition of every scene, not
  // just of building the dataset.
  await ensureDemo();

  const existing = await api('/api/recordings');
  const already = existing.body?.recordings?.find((item) => item.name === DATASET_NAME);
  if (already) {
    log(`  reusing the existing dataset "${DATASET_NAME}"`);
    return already;
  }

  const flow = {
    name: DATASET_NAME,
    mode: 'loop',
    countdown_seconds: 0.2,
    repeat: 3,
    discard_tail: 0,
    steps: [
      { label: 'eyes closed', seconds: 3 },
      { label: 'eyes open', seconds: 3 },
    ],
  };
  const started = await api('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ flow, dataset_name: DATASET_NAME, voice: false }),
  });
  if (started.status !== 201) {
    throw new Error(`could not start the showcase protocol: ${JSON.stringify(started.body)}`);
  }

  log('  recording 3 x (eyes closed 3 s / eyes open 3 s) from the synthetic source…');
  for (let i = 0; i < 120; i += 1) {
    await sleep(500);
    if ((await api('/api/sessions/current')).body === null) break;
  }

  const listing = await api('/api/recordings');
  const entry = listing.body.recordings.find((item) => item.name === DATASET_NAME);
  if (!entry) throw new Error('the showcase protocol finished but wrote no dataset');
  created.push(entry.path);
  return entry;
}

// --------------------------------------------------------------------------- stills
/** Navigate, wait for a string the screen is known to render, and let the canvases catch up. */
async function settle(url, expected, { timeout = 20000, pause = 2200 } = {}) {
  await cdp.goto(url);
  await cdp.waitFor(
    `document.body.innerText.toLowerCase().includes(${JSON.stringify(expected.toLowerCase())})`,
    { label: `"${expected}"`, timeout },
  );
  await sleep(pause);
}

/**
 * Hover or wheel-zoom a chart.
 *
 * The charts listen for real pointer events, and the coordinates have to be viewport-relative,
 * so this computes them from the element's own box — the same approach (and the same element
 * names) as the zoom check in `tools/verify-web.mjs`, which is where they were proven.
 */
async function interact(host, kind, fraction, deltaY = 0) {
  return cdp.evaluate(`(() => {
    const host = document.querySelector(${JSON.stringify(host)});
    const surface = host?.querySelector('div');
    if (!surface) return false;
    const rect = surface.getBoundingClientRect();
    const clientX = rect.left + rect.width * ${fraction};
    const clientY = rect.top + rect.height / 2;
    const cursor = document.getElementById('__lp_cursor');
    if (cursor) { cursor.style.left = clientX + 'px'; cursor.style.top = clientY + 'px'; }
    const options = { clientX, clientY, bubbles: true, cancelable: true, pointerId: 1 };
    ${
      kind === 'wheel'
        ? `surface.dispatchEvent(new WheelEvent('wheel', { ...options, deltaY: ${deltaY} }));`
        : `surface.dispatchEvent(new PointerEvent('pointermove', options));`
    }
    return true;
  })()`);
}

/**
 * Scroll before shooting.
 *
 * Several screens put the interesting thing below the fold — the library list is long enough to
 * push Discovery's charts out of a 1500px viewport, and the Run screen's "dataset written"
 * summary sits under its form. A screenshot of the top of those pages is a screenshot of a list.
 */
async function scrollTo(target) {
  if (typeof target === 'number') {
    await cdp.evaluate(`window.scrollTo(0, ${target})`);
  } else if (target === 'bottom') {
    await cdp.evaluate('window.scrollTo(0, document.body.scrollHeight)');
  } else {
    await cdp.evaluate(
      `document.querySelector(${JSON.stringify(target)})?.scrollIntoView({ block: 'start' })`,
    );
  }
  await sleep(1000); // the charts redraw on scroll
}

async function captureStills(entry) {
  log('\nstills');
  mkdirSync(STILLS_DIR, { recursive: true });

  const failures = [];
  /** Navigate, wait for a string the screen is known to render, shoot. Never fatal. */
  const still = async (name, url, expected, options = {}) => {
    try {
      await settle(url, expected, options);
      if (options.scroll !== undefined) await scrollTo(options.scroll);
      await cdp.shot(name);
      log(`  ${join(STILLS_DIR, name)}.png`);
    } catch (error) {
      failures.push(name);
      log(`  ! ${name}: ${error.message}`);
    }
  };

  await still('01-monitor', `${BASE}/`, 'montage');

  await still('03-protocols', `${BASE}/flows`, 'what it will actually do');

  // The channel reference is linkable (`?channel=O1`), but clicking a specific electrode is the
  // behaviour worth photographing — and doing both means the still survives whichever of the
  // two the route does, instead of timing out on a panel that never opened.
  try {
    await settle(`${BASE}/channels?channel=O1`, 'cms', { pause: 900 });
    const opened = await cdp.evaluate(`(() => {
      const aside = document.querySelector('aside');
      return aside ? aside.innerText.toLowerCase().includes('occipital') : false;
    })()`);
    if (!opened) {
      await cdp.evaluate(`(() => {
        const button = [...document.querySelectorAll('button')].find((candidate) =>
          /^O1\\b/.test(candidate.innerText.trim()));
        if (!button) throw new Error('no O1 button in the electrode list');
        button.click();
        return true;
      })()`);
      await cdp.waitFor(`document.body.innerText.toLowerCase().includes('occipital')`, {
        label: 'the O1 documentation',
      });
    }
    await sleep(700);
    await cdp.shot('02-channels');
    log(`  ${join(STILLS_DIR, '02-channels')}.png`);
  } catch (error) {
    failures.push('02-channels');
    log(`  ! 02-channels: ${error.message}`);
  }

  // The Run screen is only interesting while it is running, so it is photographed mid-flight
  // and then stopped. That writes a second dataset, which is cleaned up at the end.
  try {
    await settle(`${BASE}/run`, 'run a protocol', { pause: 900 });
    const started = await api('/api/sessions/quick', {
      method: 'POST',
      body: JSON.stringify({
        label: 'eyes closed',
        countdown_seconds: 3,
        voice: false,
        notes: 'screenshot for the launch post',
      }),
    });
    if (started.status !== 201) throw new Error(`run refused: ${JSON.stringify(started.body)}`);

    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('starting with')`, {
      label: 'the countdown',
      timeout: 12000,
    });
    await cdp.shot('04-run-countdown');

    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('remaining')`, {
      label: 'the recording state',
      timeout: 15000,
    });
    await sleep(7000); // long enough that the finished summary reports a real duration
    await cdp.shot('05-run-recording');

    const stopped = await api('/api/sessions/current/stop', { method: 'POST' });
    if (stopped.body?.summary) created.push(stopped.body.summary.path);

    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('dataset written')`, {
      label: 'the finished dataset',
      timeout: 12000,
    });
    await sleep(600);
    // The summary card sits below the protocol form, so shoot the bottom of the page: a
    // screenshot of an empty form says nothing.
    await scrollTo('bottom');
    await cdp.shot('06-run-finished');
    log(`  ${join(STILLS_DIR, '04..06-run')}.png`);
  } catch (error) {
    failures.push('04..06-run');
    log(`  ! run scene: ${error.message}`);
  }

  await still('07-datasets', `${BASE}/datasets`, 'library');
  await still(
    '08-dataset-states',
    `${BASE}/datasets/${encodeURIComponent(entry.id)}`,
    'states, in proportion',
  );
  await still(
    '09-discovery',
    `${BASE}/datasets/${encodeURIComponent(entry.id)}/discovery`,
    'what both states have in common',
    // Same reason as the run summary: the dataset library renders above the panel, and the
    // spectra are what this slide is about. `eeg-spectrum-overlay` is the element the zoom
    // check in verify-web.mjs already drives, so it is known to exist.
    { timeout: 30000, pause: 2600, scroll: 'eeg-spectrum-overlay' },
  );

  if (failures.length) log(`  ${failures.length} still(s) failed: ${failures.join(', ')}`);
}

// ------------------------------------------------------------------------- carousel
/**
 * Render the carousel: four authored text slides, three real screenshots, and the closing
 * slide — assembled in order into one folder, so the deck that gets uploaded is the deck that
 * was reviewed.
 */
async function captureCarousel() {
  log('\ncarousel');
  // Start from an empty folder. The deck is assembled by copying, so a slide left over from an
  // earlier run is never overwritten — it just sits there with a stale name and gets uploaded
  // by mistake.
  rmSync(CAROUSEL_DIR, { recursive: true, force: true });
  mkdirSync(CAROUSEL_DIR, { recursive: true });

  if (!existsSync(SLIDES_HTML)) throw new Error(`no ${SLIDES_HTML} — cannot render the text slides`);
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: SLIDE_SIZE.width,
    height: SLIDE_SIZE.height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.goto(pathToFileURL(SLIDES_HTML).href);
  await sleep(500);

  const slides = await cdp.evaluate(`(() => {
    return [...document.querySelectorAll('.slide')].map((element) => '#' + element.id);
  })()`);
  if (!slides.length) throw new Error('slides.html has no .slide elements');

  const rendered = [];
  for (const [index, selector] of slides.entries()) {
    const path = await cdp.shotElement(selector, `raw-${String(index + 1).padStart(2, '0')}`);
    rendered.push({ selector, path });
  }

  // Composed in reading order: 1-4 authored, 5-7 the app, 8 authored.
  const deck = [
    [rendered[0], '01-the-problem'],
    [rendered[1], '02-the-format'],
    [rendered[2], '03-the-two-bugs'],
    [rendered[3], '04-why-believe-it'],
    [join(STILLS_DIR, '01-monitor.png'), '05-the-monitor'],
    [join(STILLS_DIR, '03-protocols.png'), '06-the-protocols'],
    [join(STILLS_DIR, '09-discovery.png'), '07-the-discovery'],
    [rendered[4], '08-it-is-a-real-brain'],
  ];
  for (const [source, name] of deck) {
    const from = typeof source === 'string' ? source : source?.path;
    if (!from || !existsSync(from)) {
      log(`  ! skipped ${name} (missing ${from ?? 'slide'})`);
      continue;
    }
    copyFileSync(from, join(CAROUSEL_DIR, `${name}.png`));
    log(`  ${join(CAROUSEL_DIR, `${name}.png`)}`);
  }
  for (const { path } of rendered) rmSync(path, { force: true });
}

// ----------------------------------------------------------------------------- pdf
/**
 * Print the mixed deck to a PDF — the format LinkedIn actually accepts.
 *
 * LinkedIn removed its native carousel in 2023. A "carousel post" today is a **document post**:
 * a PDF of up to 300 pages (max 100 MB, PPT/PPTX/DOC/DOCX/PDF) that the feed renders as a
 * swipeable deck, and that viewers can also download. So the PNG slides are a review artefact;
 * this file is the one that gets uploaded.
 *
 * Reference: https://www.linkedin.com/help/linkedin/answer/a523062
 */
async function capturePdf() {
  log('\npdf');
  if (!existsSync(CAROUSEL_HTML)) throw new Error(`no ${CAROUSEL_HTML} — cannot build the PDF`);

  const missing = CAROUSEL_SHOTS.filter((name) => !existsSync(join(STILLS_DIR, `${name}.png`)));
  if (missing.length) {
    throw new Error(
      `the carousel embeds ${missing.join(', ')} — capture the screenshots first: ` +
        'npm run linkedin -- --stills',
    );
  }

  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: SLIDE_SIZE.width,
    height: SLIDE_SIZE.height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.goto(pathToFileURL(CAROUSEL_HTML).href);
  await sleep(1500); // decode a deck of full-bleed screenshots

  // A broken <img> prints as an empty frame, and an empty frame in a published carousel is
  // worse than not publishing, so this is checked rather than assumed.
  const broken = await cdp.evaluate(
    `[...document.images].filter((i) => !i.complete || i.naturalWidth === 0).map((i) => i.getAttribute('src'))`,
  );
  if (broken.length) throw new Error(`these images did not load: ${broken.join(', ')}`);

  const pages = await cdp.evaluate(`document.querySelectorAll('.slide').length`);
  if (!pages) throw new Error('carousel.html has no .slide elements');

  // Also render every page to `out/pdf-check/`. A PDF is opaque — there is no way to see a
  // clipped headline or a scrim sitting over the one interesting card without rendering it —
  // and no PDF rasteriser can be assumed to exist on the machine. These previews are the check.
  rmSync(PDF_CHECK_DIR, { recursive: true, force: true });
  mkdirSync(PDF_CHECK_DIR, { recursive: true });
  for (let index = 0; index < pages; index += 1) {
    await cdp.shotElement(
      `.slide:nth-of-type(${index + 1})`,
      String(index + 1).padStart(2, '0'),
      PDF_CHECK_DIR,
    );
  }

  const { data } = await cdp.send('Page.printToPDF', {
    printBackground: true,
    preferCSSPageSize: true, // the deck declares `@page { size: 1080px 1350px }`
    // Cosmetic, but it stops the file being metadata-less: LinkedIn asks you to type the
    // document title yourself, and everything else that opens the PDF shows this instead.
    title: PDF_TITLE,
    marginTop: 0,
    marginBottom: 0,
    marginLeft: 0,
    marginRight: 0,
  });
  const path = join(OUT, 'linkedin-carousel.pdf');
  writeFileSync(path, Buffer.from(data, 'base64'));
  log(`  ${path}  (${pages} pages)`);
  log(`  ${PDF_CHECK_DIR}  (1 PNG per page — look at these before publishing)`);
  return { output: path, pages };
}

// ------------------------------------------------------------------------- readme assets
/**
 * Copy the showcase screenshots into `docs/images/` and render the README banner.
 *
 * These are the only outputs of this tool that are **committed**. Everything else lands in
 * `linkedin/out/`, which `.gitignore` excludes as build output — but a README points at images
 * by path, so they have to exist in the repository for GitHub to render them at all.
 */
async function captureReadme() {
  log('\nreadme assets');
  mkdirSync(DOCS_IMAGES_DIR, { recursive: true });

  const picks = [
    ['01-monitor', 'monitor'],
    ['03-protocols', 'protocols'],
    ['04-run-countdown', 'run-countdown'],
    ['06-run-finished', 'run-finished'],
    ['08-dataset-states', 'dataset-states'],
    ['09-discovery', 'discovery'],
  ];
  const missing = picks
    .filter(([from]) => !existsSync(join(STILLS_DIR, `${from}.png`)))
    .map(([from]) => from);
  if (missing.length) {
    throw new Error(`missing ${missing.join(', ')} — run: npm run linkedin -- --stills`);
  }
  for (const [from, to] of picks) {
    copyFileSync(join(STILLS_DIR, `${from}.png`), join(DOCS_IMAGES_DIR, `${to}.png`));
  }
  // The closing carousel slide: the whole result in one image.
  const proof = join(CAROUSEL_DIR, '08-it-is-a-real-brain.png');
  if (existsSync(proof)) copyFileSync(proof, join(DOCS_IMAGES_DIR, 'alpha-confirmed.png'));

  // The banner, rendered after the copies above because it embeds one of them.
  if (!existsSync(HERO_HTML)) throw new Error(`no ${HERO_HTML} — cannot render the banner`);
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: HERO_SIZE.width,
    height: HERO_SIZE.height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.goto(pathToFileURL(HERO_HTML).href);
  await sleep(1200);
  const broken = await cdp.evaluate(
    `[...document.images].filter((i) => !i.complete || i.naturalWidth === 0).map((i) => i.getAttribute('src'))`,
  );
  if (broken.length) throw new Error(`hero images did not load: ${broken.join(', ')}`);
  await cdp.shotElement('#hero', 'hero', DOCS_IMAGES_DIR);

  // The demo video and the carousel PDF, committed so a reader can actually play and open them.
  // GitHub plays a repository MP4 from its own file page; a one-click player *inside* the README
  // needs a host — see the video note in README.md.
  const video = join(VIDEO_DIR, 'workbench-demo.mp4');
  if (existsSync(video)) {
    mkdirSync(join(DOCS_DIR, 'demo'), { recursive: true });
    copyFileSync(video, join(DOCS_DIR, 'demo', 'workbench-demo.mp4'));
    log(`  ${join(DOCS_DIR, 'demo', 'workbench-demo.mp4')}`);
  } else {
    log('  ! no demo video yet — run: npm run linkedin -- --video');
  }
  const carousel = join(OUT, 'linkedin-carousel.pdf');
  if (existsSync(carousel)) {
    copyFileSync(carousel, join(DOCS_DIR, 'linkedin-carousel.pdf'));
    log(`  ${join(DOCS_DIR, 'linkedin-carousel.pdf')}`);
  }

  for (const name of readdirSync(DOCS_IMAGES_DIR).filter((f) => f.endsWith('.png')).sort()) {
    log(`  ${join(DOCS_IMAGES_DIR, name)}`);
  }
  return { images: readdirSync(DOCS_IMAGES_DIR).filter((f) => f.endsWith('.png')).sort() };
}

// ---------------------------------------------------------------------------- video
/**
 * The tour. Each step is a labelled async function so one broken interaction cannot cost the
 * whole recording: a failing step is reported and the tour continues to the next scene.
 */
function tour(entry) {
  return [
    [
      'intro card',
      async () => {
        // The page is already on the monitor and already has samples (see captureVideo), so
        // this must NOT navigate: a reload here would open the video on a white flash.
        await cdp.showCard(
          'Raw EEG from an Emotiv EPOC+',
          '14 channels · 128 Hz · no Emotiv software · no licence',
        );
        await sleep(2600);
        await cdp.hideCard();
      },
    ],
    [
      'monitor — the live signal',
      async () => {
        await sleep(2600);
        await cdp.evaluate('window.scrollTo({ top: 0, behavior: "smooth" })');
        await sleep(600);
        // The monitor is the tall page: a slow scroll shows the traces, the contact map and
        // the alpha meter without a single click, which is what "it is live" looks like.
        for (let i = 0; i < 5; i += 1) {
          await cdp.evaluate('window.scrollBy({ top: 260, behavior: "smooth" })');
          await sleep(900);
        }
        await cdp.evaluate('window.scrollTo({ top: 0, behavior: "smooth" })');
        await sleep(1400);
      },
    ],
    [
      'channels — the electrode reference',
      async () => {
        await settle(`${BASE}/channels`, 'cms', { pause: 1200 });
        // Click through two electrodes rather than trusting the query parameter to preselect:
        // the click is the interaction that shows the panel is real documentation, not a mock.
        for (const channel of ['O1', 'O2']) {
          await cdp.evaluate(`(() => {
            const button = [...document.querySelectorAll('button')].find((candidate) =>
              new RegExp('^' + ${JSON.stringify(channel)} + '\\\\b').test(candidate.innerText.trim()));
            if (button) button.click();
            return Boolean(button);
          })()`);
          await sleep(2400);
        }
      },
    ],
    [
      'protocols — building a guided run',
      async () => {
        await settle(`${BASE}/flows`, 'what it will actually do', { pause: 1800 });
        for (let i = 0; i < 3; i += 1) {
          await cdp.evaluate('window.scrollBy({ top: 240, behavior: "smooth" })');
          await sleep(800);
        }
        await sleep(1600);
        await cdp.evaluate('window.scrollTo({ top: 0, behavior: "smooth" })');
        await sleep(900);
      },
    ],
    [
      'run — countdown, recording, dataset written',
      async () => {
        await settle(`${BASE}/run`, 'run a protocol', { pause: 900 });
        const started = await api('/api/sessions/quick', {
          method: 'POST',
          body: JSON.stringify({
            label: 'eyes closed',
            countdown_seconds: 3,
            voice: false,
            notes: 'recorded by tools/linkedin-capture.mjs',
          }),
        });
        if (started.status !== 201) throw new Error(`run refused: ${JSON.stringify(started.body)}`);
        await cdp.waitFor(`document.body.innerText.toLowerCase().includes('starting with')`, {
          label: 'the countdown',
          timeout: 12000,
        });
        await sleep(2800);
        await cdp.waitFor(`document.body.innerText.toLowerCase().includes('remaining')`, {
          label: 'the recording state',
          timeout: 15000,
        });
        await sleep(4200);
        const stopped = await api('/api/sessions/current/stop', { method: 'POST' });
        if (stopped.body?.summary) created.push(stopped.body.summary.path);
        await sleep(2400);
      },
    ],
    [
      'datasets — the label timeline and the spectrum',
      async () => {
        await settle(`${BASE}/datasets/${encodeURIComponent(entry.id)}`, 'states, in proportion', {
          pause: 2000,
        });
        await cdp.evaluate(`(() => {
          const row = document.querySelector('table tbody tr');
          if (row) row.click();
          return Boolean(row);
        })()`);
        await sleep(2600);
      },
    ],
    [
      'discovery — where the two states differ',
      async () => {
        await settle(`${BASE}/datasets/${encodeURIComponent(entry.id)}/discovery`, 'what both states have in common', {
          timeout: 30000,
          pause: 3000,
        });
        // Hover, then zoom into the band the demo injected its difference in. These two
        // element names and the zoom control are the ones verify-web.mjs already exercises.
        await interact('eeg-spectrum-overlay', 'pointermove', 0.32);
        await sleep(1400);
        await interact('eeg-spectrum-overlay', 'wheel', 0.32, -260);
        await sleep(2200);
        await interact('eeg-spectrum-overlay', 'wheel', 0.42, -200);
        await sleep(2600);
      },
    ],
    [
      'closing card',
      async () => {
        await cdp.showCard(
          'Alpha rhythm confirmed — the signal is a real brain',
          'github.com/titusfx/brain-waves-projects · MIT · credited to emokit',
        );
        await sleep(3600);
        await cdp.hideCard();
      },
    ],
  ];
}

async function captureVideo(entry) {
  log('\nvideo');
  mkdirSync(VIDEO_DIR, { recursive: true });
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: VIDEO_SIZE.width,
    height: VIDEO_SIZE.height,
    deviceScaleFactor: 1,
    mobile: false,
  });

  // Land on the monitor and let it draw *before* the screencast opens, so the first frame of
  // the video is the app rather than whatever the stills or carousel passes left on screen.
  await settle(`${BASE}/`, 'montage', { pause: 1800 });

  await cdp.startRecording({ ...VIDEO_SIZE, quality: VIDEO_QUALITY });
  await cdp.enableCursor();

  for (const [label, step] of tour(entry)) {
    log(`  · ${label}`);
    try {
      await step();
    } catch (error) {
      // Never abort the take: a scene that fails is one missing beat, not a lost recording.
      log(`    ! ${label} failed: ${error.message}`);
    }
  }

  const frames = await cdp.stopRecording();
  if (!frames.length) throw new Error('the screencast produced no frames');
  log(`  captured ${frames.length} frames`);

  const seconds = (frames.at(-1).at - frames[0].at) / 1000;
  const listPath = join(FRAMES_DIR, 'frames.txt');
  const lines = [];
  for (const [index, frame] of frames.entries()) {
    const next = frames[index + 1];
    const duration = next ? (next.at - frame.at) / 1000 : 1 / 30;
    // Clamp: a stalled frame would otherwise hold the whole video on one image.
    lines.push(`file 'f${String(frame.index).padStart(5, '0')}.jpg'`);
    lines.push(`duration ${Math.min(Math.max(duration, 1 / 60), 1).toFixed(4)}`);
  }
  // The concat demuxer ignores the final `duration` unless the last file is listed twice.
  lines.push(`file 'f${String(frames.at(-1).index).padStart(5, '0')}.jpg'`);
  writeFileSync(listPath, `${lines.join('\n')}\n`);

  const output = join(VIDEO_DIR, 'workbench-demo.mp4');
  const filter =
    `scale=${VIDEO_SIZE.width}:${VIDEO_SIZE.height}:force_original_aspect_ratio=decrease,` +
    `pad=${VIDEO_SIZE.width}:${VIDEO_SIZE.height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p`;
  const args = [
    '-y',
    '-f', 'concat',
    '-safe', '0',
    '-i', listPath,
    '-an',
    '-vf', filter,
    '-r', '30',
    '-c:v', 'libx264',
    '-preset', 'medium',
    '-crf', '20',
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    output,
  ];

  if (!FFMPEG) {
    const script = join(VIDEO_DIR, 'encode-video.ps1');
    writeFileSync(
      script,
      [
        '# ffmpeg was not on PATH when the frames were captured.',
        '# Install it ( winget install Gyan.FFmpeg ) and run this, or set FFMPEG_PATH and',
        '# re-run:  npm run linkedin -- --video',
        `ffmpeg ${args.map((value) => (value.includes(' ') ? `"${value}"` : value)).join(' ')}`,
        '',
      ].join('\n'),
    );
    log(`  ! ffmpeg not found — ${frames.length} frames kept in ${FRAMES_DIR}`);
    log(`    install ffmpeg and run ${script}`);
    return { output: null, frames: frames.length, seconds };
  }

  log('  encoding with ffmpeg…');
  const encoded = spawnSync(FFMPEG, args, { stdio: 'inherit' });
  if (encoded.status !== 0) throw new Error(`ffmpeg exited ${encoded.status}`);
  log(`  ${output}  (~${seconds.toFixed(1)}s, ${VIDEO_SIZE.width}x${VIDEO_SIZE.height})`);
  rmSync(FRAMES_DIR, { recursive: true, force: true });
  return { output, frames: frames.length, seconds };
}

// --------------------------------------------------------------------------- main
const profile = mkdtempSync(join(tmpdir(), 'eeg-linkedin-'));
mkdirSync(OUT, { recursive: true });

let entry;
let video = null;
let pdf = null;
let readme = null;
try {
  const health = await api('/health');
  if (health.status !== 200) {
    throw new Error(
      `${BASE}/health returned ${health.status}. Start the app first: ` +
        'npm run build:web && npm run api:prod',
    );
  }
  const status = await api('/api/system/status');
  log(`serving ${BASE} · source is "${status.body?.source}"`);
  if (status.body?.source === 'live') {
    log('switching the dongle off — nothing recorded for a public post is a real head');
  }

  log('\ndataset');
  entry = await buildShowcaseDataset();
  log(`  ${entry.id}  (${entry.name})`);

  chrome = spawn(
    CHROME,
    [
      '--headless=new',
      `--remote-debugging-port=${CDP_PORT}`,
      `--user-data-dir=${profile}`,
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-gpu',
      '--hide-scrollbars',
      '--mute-audio',
      `--window-size=${Math.max(STILL_SIZE.width, VIDEO_SIZE.width)},${Math.max(STILL_SIZE.height, VIDEO_SIZE.height)}`,
      'about:blank',
    ],
    { stdio: 'ignore' },
  );

  const deadline = Date.now() + 25000;
  for (;;) {
    try {
      if ((await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).ok) break;
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) throw new Error('Chrome did not expose a debugging port');
    await sleep(250);
  }
  cdp = await openTarget();

  if (WANT_STILLS) {
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: STILL_SIZE.width,
      height: STILL_SIZE.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await captureStills(entry);
    await captureCarousel();
  }

  if (WANT_PDF) pdf = await capturePdf();

  if (WANT_README) readme = await captureReadme();

  if (WANT_VIDEO) video = await captureVideo(entry);

  const manifest = {
    base: BASE,
    recordedAt: new Date().toISOString(),
    note: 'All footage is the synthetic demo source, labelled demo in the app. Not a person.',
    dataset: { id: entry.id, name: entry.name },
    stills: WANT_STILLS ? readdirSync(STILLS_DIR).filter((f) => f.endsWith('.png')).sort() : [],
    carousel: WANT_STILLS ? readdirSync(CAROUSEL_DIR).filter((f) => f.endsWith('.png')).sort() : [],
    video,
    pdf,
    readme,
  };
  writeFileSync(join(OUT, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);

  log(`\ndone → ${OUT}`);
  log('  before publishing: confirm every frame shows "demo", and that the video is under 90 s.');
} catch (error) {
  console.error(`\nfailed: ${error.message}`);
  process.exitCode = 1;
} finally {
  cdp?.socket?.close?.();
  chrome?.kill();
  // Chrome does not release its profile the instant it is signalled, so deleting it straight
  // away can throw EPERM — which used to turn a completely successful run into a non-zero
  // exit, after every asset had already been written. Best effort, retried.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      rmSync(profile, { recursive: true, force: true });
      break;
    } catch {
      await sleep(300);
    }
  }

  if (!KEEP_DATASET && created.length) {
    log('\ncleaning up the synthetic datasets this run wrote');
    for (const path of created) {
      const id = String(path).split(/[\\/]/).pop();
      const deleted = await api(`/api/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' });
      log(`  ${deleted.status === 200 ? 'removed' : `left (${deleted.status})`}  ${id}`);
    }
    log('  (--keep-dataset keeps them)');
  }
}
