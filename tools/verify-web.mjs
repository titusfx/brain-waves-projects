#!/usr/bin/env node
/**
 * verify-web.mjs â€” drive the built workbench in a real browser and assert it works.
 *
 * Why this exists: everything else in this repository can be checked by a test, but
 * "does the operator actually see a signal" cannot. A canvas that draws nothing, a
 * WebSocket that never connects, an Angular template that throws only at runtime â€” all
 * of those pass a unit test and fail the person using the app. So this launches Chrome
 * over the DevTools protocol, loads the pages the app *serves* (not a dev server),
 * asserts against the rendered DOM and the pixels on the canvases, records every
 * console error, and writes screenshots to look at.
 *
 * No dependencies: Node's own WebSocket and `fetch` are enough for CDP.
 *
 *   node tools/verify-web.mjs
 *   BASE_URL=http://127.0.0.1:4301 node tools/verify-web.mjs    # against `ng serve`
 *
 * Exit code 0 means every assertion passed and the console was clean.
 *
 * It records a real dataset while checking the run screen, then deletes that one
 * directory again â€” the checks are on the app, not on the operator's library.
 */
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8020';
const OUT = process.env.OUT_DIR ?? 'tools/out-verify';
const CDP_PORT = Number(process.env.CDP_PORT ?? 9333);
const CHROME =
  process.env.CHROME_PATH ??
  [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].find((path) => existsSync(path));

if (!CHROME) {
  console.error('no Chrome found; set CHROME_PATH');
  process.exit(2);
}

const results = [];
const consoleErrors = [];
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/** Dataset directories this run wrote, removed again on the way out. */
const createdDatasets = [];

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function check(name, fn) {
  try {
    results.push({ name, ok: true, value: await fn() });
  } catch (error) {
    results.push({ name, ok: false, error: String(error.message ?? error) });
  }
}

/**
 * Runs in the page. Everything it returns must be JSON-serialisable.
 *
 * Note `innerText.toLowerCase()`: Chrome returns text *after* CSS `text-transform`, and
 * the UI renders section headings in uppercase, so comparing raw text against
 * "Montage" silently never matches.
 */
const PAGE_PROBE = `(() => {
  const raw = document.body.innerText;
  const text = raw.toLowerCase();
  const canvases = [...document.querySelectorAll('canvas')].map((canvas) => {
    const ctx = canvas.getContext('2d');
    let ink = 0;
    if (ctx && canvas.width && canvas.height) {
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < data.length; i += 4 * 53) {
        if (data[i] + data[i + 1] + data[i + 2] > 60) ink += 1;
      }
    }
    return { width: canvas.width, height: canvas.height, ink };
  });
  return {
    text,
    canvases,
    title: document.title,
    rows: document.querySelectorAll('table tbody tr').length,
  };
})()`;

// --------------------------------------------------------------------------- CDP
class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
        return;
      }
      if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
        consoleErrors.push(
          message.params.args.map((a) => a.value ?? a.description ?? a.type).join(' '),
        );
      }
      if (message.method === 'Runtime.exceptionThrown') {
        const details = message.params.exceptionDetails;
        consoleErrors.push(details.exception?.description ?? details.text);
      }
      if (this.onEvent) this.onEvent(message);
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
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

  async waitFor(expression, { timeout = 8000, label = expression } = {}) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await this.evaluate(`Boolean(${expression})`)) return true;
      await sleep(120);
    }
    throw new Error(`timed out waiting for ${label}`);
  }

  async goto(url) {
    const loaded = new Promise((resolve) => {
      this.onEvent = (message) => {
        if (message.method === 'Page.loadEventFired') {
          this.onEvent = null;
          resolve();
        }
      };
    });
    await this.send('Page.navigate', { url });
    await loaded;
  }

  async shot(name) {
    const { data } = await this.send('Page.captureScreenshot', { format: 'png' });
    const path = join(OUT, `${name}.png`);
    writeFileSync(path, Buffer.from(data, 'base64'));
    return path;
  }

  /**
   * Write what the page *says*, alongside the screenshot.
   *
   * The screenshots are for a person; this is for anything that has to reason about the
   * page without looking at a picture â€” and it is the only way to notice that a panel
   * rendered the right heading above the wrong numbers.
   */
  async dump(name) {
    const text = await this.evaluate('document.body.innerText');
    writeFileSync(join(OUT, `${name}.txt`), `${text}\n`);
    return text;
  }
}

async function openTarget() {
  // Chrome 111+ requires PUT for /json/new.
  const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/new?about:blank`, {
    method: 'PUT',
  });
  const target = await response.json();
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  const cdp = new Cdp(socket);
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Log.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1500,
    height: 1000,
    deviceScaleFactor: 1,
    mobile: false,
  });
  return cdp;
}

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
 * Make sure the synthetic signal is running, and return the mode that was found first.
 *
 * Any check that needs samples must call this rather than assume the previous check left
 * a useful source: a check that records from a silent dongle reports "0 samples" and
 * looks like a bug in the recorder.
 */
async function ensureDemo() {
  const before = (await api('/api/system/status')).body.source;
  if (before !== 'demo') {
    await api('/api/system/source', { method: 'POST', body: JSON.stringify({ mode: 'demo' }) });
  }
  for (let i = 0; i < 60; i += 1) {
    const status = await api('/api/system/status');
    if (status.body.stats.samples >= 64) return before;
    await sleep(150);
  }
  throw new Error(`the demo source produced no samples (source was ${before})`);
}

// --------------------------------------------------------------------------- main
const profile = mkdtempSync(join(tmpdir(), 'eeg-verify-'));
mkdirSync(OUT, { recursive: true });

const chrome = spawn(
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
    'about:blank',
  ],
  { stdio: 'ignore' },
);

let cdp;
try {
  const deadline = Date.now() + 20000;
  for (;;) {
    try {
      const response = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      if (response.ok) break;
    } catch {
      /* not up yet */
    }
    if (Date.now() > deadline) throw new Error('Chrome did not expose a debugging port');
    await sleep(250);
  }

  cdp = await openTarget();

  // A previous interrupted run can leave a session running, which blocks the source
  // switch and puts the run screen in its "recording" state. Clear it first.
  await check('no session is left over from an earlier run', async () => {
    const current = await api('/api/sessions/current');
    if (current.body) {
      await api('/api/sessions/current/abort', { method: 'POST' });
      await sleep(300);
    }
    const after = await api('/api/sessions/current');
    assert(after.body === null, `a session is still running: ${JSON.stringify(after.body)}`);
    return { cleaned: Boolean(current.body) };
  });

  await check('the API is serving the built app', async () => {
    const health = await api('/health');
    assert(health.status === 200, `/health returned ${health.status}`);
    const index = await fetch(`${BASE}/`);
    const html = await index.text();
    assert(index.status === 200, `GET / returned ${index.status}`);
    assert(html.includes('eeg-root'), 'the served page is not the Angular shell');
    return health.body;
  });

  await check('the dongle is either streaming or honestly explained', async () => {
    // This check has to hold in three states, and it must never fail for the *right*
    // reason: no dongle attached, a dongle attached with the headset off (the state that
    // makes a person conclude "the app is broken"), and a dongle that is genuinely
    // streaming. `default_source: auto` means any of them can be what the app boots into.
    const started = await api('/api/system/source', {
      method: 'POST',
      body: JSON.stringify({ mode: 'live' }),
    });
    const present = Boolean(started.body.device?.present);

    // Give the headset a moment to be heard, then decide which state we are in.
    let samples = 0;
    for (let i = 0; i < 30 && samples === 0; i += 1) {
      const status = await api('/api/system/status');
      samples = status.body.stats.samples;
      if (samples === 0) await sleep(200);
    }

    await cdp.goto(`${BASE}/`);
    const page = await cdp.evaluate(PAGE_PROBE);

    if (!present) {
      await cdp.waitFor(`document.body.innerText.toLowerCase().includes('nothing is streaming')`, {
        label: 'the idle notice',
        timeout: 12000,
      });
      await cdp.shot('0-no-dongle');
      await cdp.dump('0-no-dongle');
      return { donglePresent: false };
    }

    if (samples > 0) {
      // The real thing: a headset, over RF, through the decoder, into the browser.
      await cdp.waitFor(`document.querySelectorAll('table tbody tr').length === 14`, {
        label: 'the channel table for the live headset',
        timeout: 15000,
      });
      const live = await cdp.evaluate(PAGE_PROBE);
      assert(live.text.includes('dongle'), 'the header does not name the dongle source');
      assert(live.text.includes('reports/s'), 'the source strip is missing');
      const keyRow = await api('/api/system/status');
      assert(
        keyRow.body.stats.reports_per_second > 100,
        `only ${keyRow.body.stats.reports_per_second} reports/s; the dongle should send ~159`,
      );
      assert(
        keyRow.body.stats.key_ok !== false,
        `the byte-1 key oracle says WRONG KEY (${keyRow.body.stats.distinct_byte1} distinct values)`,
      );
      await cdp.shot('0-dongle-live');
      await cdp.dump('0-dongle-live');
      return {
        donglePresent: true,
        streaming: true,
        samples: keyRow.body.stats.samples,
        reportsPerSecond: keyRow.body.stats.reports_per_second,
        keyOk: keyRow.body.stats.key_ok,
      };
    }

    // Attached and silent: the RF/pairing checklist, not the cable.
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('zero reports')`, {
      label: 'the pairing checklist',
      timeout: 12000,
    });
    const silent = await cdp.evaluate(PAGE_PROBE);
    assert(silent.text.includes('switched on'), 'the checklist omits the headset power switch');
    assert(silent.text.includes('pairing'), 'the checklist omits pairing');
    assert(silent.text.includes('fast-flashing'), 'the checklist omits the dongle LEDs');
    await cdp.shot('0-dongle-silent');
    await cdp.dump('0-dongle-silent');
    return { donglePresent: true, streaming: false };
  });

  await check('the demo source starts and produces samples', async () => {
    const started = await api('/api/system/source', {
      method: 'POST',
      body: JSON.stringify({ mode: 'demo' }),
    });
    assert(started.status === 200, `source switch returned ${started.status}`);
    assert(started.body.source === 'demo', `source is ${started.body.source}`);
    for (let i = 0; i < 60; i += 1) {
      const status = await api('/api/system/status');
      if (status.body.stats.samples > 200) return { samples: status.body.stats.samples };
      await sleep(150);
    }
    throw new Error('the demo source produced no samples');
  });

  // --------------------------------------------------------------- monitor
  await check('the monitor renders a live signal', async () => {
    await cdp.goto(`${BASE}/`);
    await cdp.waitFor(`document.querySelectorAll('table tbody tr').length === 14`, {
      label: 'the 14-channel table',
    });
    await sleep(1500); // a few ticks of samples for the canvases
    const page = await cdp.evaluate(PAGE_PROBE);
    assert(page.rows === 14, `expected 14 channel rows, saw ${page.rows}`);
    assert(page.text.includes('montage'), 'the montage map is missing');
    assert(page.text.includes('alpha 8'), 'the alpha meter is missing');
    assert(page.text.includes('demo signal'), 'the header does not name the demo source');
    assert(page.text.includes('reports/s'), 'the source strip is missing');
    // One canvas: the trace strips. The montage is SVG (so it can be clicked per
    // electrode), and the bars and meters are DOM.
    assert(page.canvases.length >= 1, `expected a trace canvas, saw ${page.canvases.length}`);
    const blank = page.canvases.filter((canvas) => canvas.ink === 0);
    assert(blank.length === 0, `${blank.length} canvas(es) drew nothing`);
    await cdp.shot('1-monitor');
    await cdp.dump('1-monitor');
    return {
      rows: page.rows,
      canvases: page.canvases.map((canvas) => `${canvas.width}x${canvas.height} ink=${canvas.ink}`),
    };
  });

  // -------------------------------------------------------------- channels
  await check('the channel reference documents all 14 sites', async () => {
    await cdp.goto(`${BASE}/channels`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('cms')`, {
      label: 'the catalog',
    });
    const page = await cdp.evaluate(PAGE_PROBE);
    const names = ['f3', 'fc5', 'af3', 'f7', 't7', 'p7', 'o1', 'o2', 'p8', 't8', 'f8', 'af4', 'fc6', 'f4'];
    const missing = names.filter((name) => !page.text.includes(name));
    assert(missing.length === 0, `undocumented: ${missing.join(', ')}`);
    assert(page.text.includes('common mode sense'), 'the reference pads are not explained');
    assert(page.text.includes('delta') && page.text.includes('gamma'), 'the band legend is missing');
    assert(page.text.includes('not a clinical tool'), 'the disclaimer is missing');
    await cdp.shot('2-channels');
    await cdp.dump('2-channels');
    return { channels: names.length };
  });

  await check('clicking a channel shows its documentation and updates the URL', async () => {
    await cdp.evaluate(`(() => {
      const button = [...document.querySelectorAll('button')].find((candidate) =>
        /^O1\\b/.test(candidate.innerText.trim()));
      if (!button) throw new Error('no O1 button in the electrode list');
      button.click();
      return true;
    })()`);
    await cdp.waitFor(`location.search.includes('channel=O1')`, { label: 'the URL to change' });
    await sleep(500);
    const panel = await cdp.evaluate(
      `(() => { const aside = document.querySelector('aside'); return aside ? aside.innerText.toLowerCase() : ''; })()`,
    );
    assert(panel.includes('alpha'), 'the O1 documentation does not mention alpha');
    assert(panel.includes('occipital'), 'the O1 documentation does not place it over the occipital pole');
    assert(panel.includes('what ruins it'), 'the artefact section is missing');
    return { excerpt: panel.slice(0, 140).replace(/\s+/g, ' ') };
  });

  // ----------------------------------------------------------------- flows
  await check('the protocol builder previews a running order', async () => {
    await cdp.goto(`${BASE}/flows`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('what it will actually do')`, {
      label: 'the builder',
    });
    await sleep(900); // the preview request is debounced
    const state = await cdp.evaluate(`(() => {
      const text = document.body.innerText;
      const chips = [...document.querySelectorAll('ol li')].map((li) => li.innerText.trim());
      return {
        seedsListed: text.includes('Eyes closed / eyes open') && text.includes('Lie down'),
        valid: /valid/i.test(text),
        phases: chips.length,
        sample: chips.slice(0, 6),
      };
    })()`);
    assert(state.seedsListed, 'the seeded protocols are not listed');
    assert(state.valid, 'the seeded protocol did not validate');
    assert(state.phases >= 4, `the timeline shows only ${state.phases} phases`);
    await cdp.shot('3-flows');
    await cdp.dump('3-flows');
    return state;
  });

  await check('an unrunnable protocol is rejected with a reason', async () => {
    const response = await api('/api/flows/validate', {
      method: 'POST',
      body: JSON.stringify({
        name: 'bad',
        mode: 'loop',
        steps: [{ label: 'forever', seconds: null }],
      }),
    });
    assert(response.body.valid === false, 'an unrunnable protocol validated');
    assert(
      response.body.errors.some((message) => message.includes('never advance')),
      `unhelpful error: ${JSON.stringify(response.body.errors)}`,
    );
    return response.body;
  });

  // ------------------------------------------------------------------- run
  await check('a protocol counts down, records, and writes a dataset', async () => {
    // A check that records a dataset has to establish that there is a signal to record,
    // rather than inheriting whatever source an earlier check left behind — otherwise it
    // tests the environment instead of the app, and fails with "0 samples recorded" when
    // the dongle happens to be selected and the headset happens to be off.
    const sourceMode = await ensureDemo();
    await cdp.goto(`${BASE}/run`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('run a protocol')`, {
      label: 'the run screen',
    });
    await sleep(600);

    const started = await api('/api/sessions/quick', {
      method: 'POST',
      body: JSON.stringify({
        label: 'eyes closed',
        countdown_seconds: 3,
        voice: false,
        notes: 'written by tools/verify-web.mjs',
      }),
    });
    assert(started.status === 201, `session start returned ${started.status}`);

    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('starting with')`, {
      label: 'the countdown overlay',
    });
    const countdown = await cdp.evaluate(`(() => {
      const match = document.body.innerText.match(/starting with\\s*\\n?\\s*(\\d+)/i);
      return { number: match ? Number(match[1]) : null };
    })()`);
    assert(countdown.number !== null, 'the countdown shows no number');
    assert(countdown.number <= 3 && countdown.number >= 1, `countdown showed ${countdown.number}`);
    await cdp.shot('4-run-countdown');

    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('remaining')`, {
      label: 'the recording state',
      timeout: 12000,
    });
    const recording = await cdp.evaluate(`(() => {
      const text = document.body.innerText.toLowerCase();
      return {
        recording: text.includes('recording'),
        labelled: text.includes('eyes closed'),
        hasRing: Boolean(document.querySelector('svg circle[stroke-dasharray]')),
      };
    })()`);
    assert(recording.recording, 'the page never reported that it was recording');
    assert(recording.labelled, 'the current state label is not shown');
    assert(recording.hasRing, 'the phase progress ring is missing');
    await sleep(1800);

    // Recording silence produces a dataset that looks fine and means nothing, so check
    // that samples are actually arriving, both from the source and into the recorder.
    // The second is the one that catches a recorder writing nothing while the session
    // reports that it is recording.
    const live = await api('/api/system/status');
    assert(
      live.body.stats.samples > 64,
      `the source (${live.body.source}, was ${sourceMode}) produced ` +
        `${live.body.stats.samples} samples; the recording cannot be checked`,
    );
    const recordingNow = await api('/api/sessions/current');
    const captured = recordingNow.body?.recording_state?.samples ?? 0;
    assert(
      captured > 128,
      `the session says it is recording but has captured ${captured} samples`,
    );
    await cdp.shot('5-run-recording');
    await cdp.dump('5-run-recording');

    const stopped = await api('/api/sessions/current/stop', { method: 'POST' });
    assert(stopped.status === 200, `stop returned ${stopped.status}`);
    const summary = stopped.body.summary;
    assert(summary, 'stopping produced no dataset summary');
    assert(summary.samples > 100, `only ${summary.samples} samples were recorded`);
    assert(summary.kept_segments.length === 1, `expected 1 kept state, got ${summary.kept_segments.length}`);
    assert(summary.kept_segments[0].label === 'eyes closed', `labelled ${summary.kept_segments[0].label}`);
    createdDatasets.push(summary.path);

    await sleep(700);
    const finished = await cdp.evaluate(
      `document.body.innerText.toLowerCase().includes('dataset written')`,
    );
    assert(finished, 'the run screen did not report the finished dataset');
    await cdp.shot('6-run-finished');
    return { sourceBefore: sourceMode, countdown: countdown.number, samples: summary.samples, labels: summary.labels };
  });

  await check('the countdown was not written into the dataset', async () => {
    assert(createdDatasets.length, 'no dataset was created');
    const id = createdDatasets[0].split(/[\\/]/).pop();
    const segments = await api(`/api/recordings/${encodeURIComponent(id)}/segments`);
    assert(segments.status === 200, `segments returned ${segments.status}`);
    assert(segments.body.length === 1, `expected 1 labelled state, got ${segments.body.length}`);
    const first = segments.body[0];
    assert(
      first.start_sample === 0,
      `the state starts at sample ${first.start_sample}, not 0 â€” the countdown leaked in`,
    );
    return first;
  });

  // -------------------------------------------------------------- datasets
  await check('the dataset browser shows labels, samples and a spectrum', async () => {
    await cdp.goto(`${BASE}/datasets`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('library')`, {
      label: 'the library',
    });
    await sleep(2000); // preview + spectrum requests
    const page = await cdp.evaluate(PAGE_PROBE);
    assert(page.text.includes('eyes closed'), 'the dataset is not listed');
    assert(page.text.includes('states, in proportion'), 'the label timeline is missing');
    assert(page.text.includes('spectrum'), 'the spectrum panel is missing');
    assert(page.rows >= 1, 'the segment table is empty');
    assert(page.canvases.length >= 2, `expected 2 charts, saw ${page.canvases.length}`);
    const blank = page.canvases.filter((canvas) => canvas.ink === 0);
    assert(blank.length === 0, `${blank.length} chart(s) drew nothing`);
    await cdp.shot('7-datasets');
    await cdp.dump('7-datasets');
    return { rows: page.rows, canvases: page.canvases.length };
  });

  // ------------------------------------------------------------- discovery
  await check('discovery finds the alpha difference the protocol created', async () => {
    // A two-state protocol run against the demo source. The runner tells the synthetic
    // subject to close its eyes on the "eyes closed" states, so the dataset genuinely
    // contains an alpha difference — which means this one check exercises the whole
    // chain: protocol → signal → dataset → analysis → screen.
    await ensureDemo();
    const flow = {
      name: 'discovery probe',
      mode: 'loop',
      countdown_seconds: 0.2,
      repeat: 3,
      discard_tail: 0,
      steps: [
        { label: 'eyes closed', seconds: 2.5 },
        { label: 'eyes open', seconds: 2.5 },
      ],
    };
    const created = await api('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ flow, dataset_name: 'verify discovery', voice: false }),
    });
    assert(created.status === 201, `session start returned ${created.status}`);

    // Six states of 2.5 s plus the countdown: wait for it to finish on its own.
    let finished = false;
    for (let i = 0; i < 60 && !finished; i += 1) {
      await sleep(500);
      finished = (await api('/api/sessions/current')).body === null;
    }
    assert(finished, 'the discovery protocol never finished');

    const listing = await api('/api/recordings');
    const entry = listing.body.recordings.find((item) => item.name === 'verify discovery');
    assert(entry, 'the discovery dataset was not written');
    createdDatasets.push(entry.path);

    const analysis = await api(`/api/recordings/${encodeURIComponent(entry.id)}/discovery`, {
      method: 'POST',
      body: JSON.stringify({
        channel: 'O1',
        labels: ['eyes closed', 'eyes open'],
        min_seconds: 2,
        permutations: 200,
      }),
    });
    assert(analysis.status === 200, `discovery returned ${analysis.status}: ${analysis.body?.detail}`);
    const body = analysis.body;
    assert(body.classes.length === 2, 'expected two states to compare');
    assert(
      body.classes[0].summary.n >= 2 && body.classes[1].summary.n >= 2,
      'the analysis needs at least two instances per state',
    );

    const comparison = body.comparison;
    assert(comparison?.reliable, 'the comparison is not reliable with this many instances');
    const peak = comparison.effect.indexOf(Math.max(...comparison.effect));
    const bestHz = comparison.freqs[peak];
    assert(
      bestHz >= 8 && bestHz <= 13,
      `the biggest difference was found at ${bestHz} Hz, not in the alpha band`,
    );
    assert(
      comparison.shared_count < comparison.effect.length,
      'every bin was reported as shared, so nothing was found at all',
    );
    // Six states across two labels is 20 ways to split them, so ~0.048 is the floor.
    assert(
      comparison.min_attainable_p <= 0.05,
      `the attainable p is ${comparison.min_attainable_p}, which no result could clear`,
    );
    assert(
      comparison.separability.available,
      'a separability readout should be possible with three instances a side',
    );
    const topChannel = body.channel_ranking[0]?.channel;
    assert(
      topChannel === 'O1' || topChannel === 'O2',
      `the states separate best at ${topChannel}, which is not where the alpha was put`,
    );

    // And the screen has to show it.
    await cdp.goto(`${BASE}/datasets/${entry.id}/discovery`);
    await cdp.waitFor(
      `document.body.innerText.toLowerCase().includes('what both states have in common')`,
      { label: 'the discovery panel', timeout: 20000 },
    );
    await sleep(1500);
    const page = await cdp.evaluate(PAGE_PROBE);
    assert(page.text.includes('shuffling the state labels'), 'the shuffle readout is missing');
    assert(page.text.includes('nearest-centroid'), 'the separability readout is missing');
    assert(page.text.includes('same in both'), 'the shared-bin summary is missing');
    assert(page.canvases.length >= 2, `expected 2 charts, saw ${page.canvases.length}`);
    const blank = page.canvases.filter((canvas) => canvas.ink === 0);
    assert(blank.length === 0, `${blank.length} discovery chart(s) drew nothing`);
    await cdp.shot('8-discovery');
    await cdp.dump('8-discovery');

    return {
      instancesPerState: body.classes[0].summary.n,
      differenceAtHz: bestHz,
      effect: comparison.observed_max_effect,
      pValue: comparison.p_value,
      minAttainableP: comparison.min_attainable_p,
      sharedBins: comparison.shared_count,
      bestChannel: topChannel,
    };
  });

  await check('a single state can be shown on its own', async () => {
    // Clicking a state narrows the samples and the spectrum to that state's window.
    const listing = await api('/api/recordings');
    const entry = listing.body.recordings.find((item) => item.name === 'verify discovery');
    assert(entry, 'the discovery dataset is missing');
    const segments = await api(`/api/recordings/${encodeURIComponent(entry.id)}/segments`);
    const first = segments.body[0];

    const whole = await api(`/api/recordings/${encodeURIComponent(entry.id)}/preview?points=400`);
    const window_ = await api(
      `/api/recordings/${encodeURIComponent(entry.id)}/preview?points=400&start=${first.start_time}&end=${first.end_time}`,
    );
    assert(
      window_.body.total_samples < whole.body.total_samples,
      'narrowing to one state did not narrow the samples',
    );
    assert(
      window_.body.total_samples > 0,
      'narrowing to one state returned nothing at all',
    );

    await cdp.goto(`${BASE}/datasets/${entry.id}`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('states, in proportion')`, {
      label: 'the dataset overview',
    });
    await cdp.evaluate(`(() => {
      const cells = [...document.querySelectorAll('table tbody tr')];
      if (!cells.length) throw new Error('no state rows to click');
      cells[0].click();
      return true;
    })()`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('whole recording')`, {
      label: 'the selected-state chip',
    });
    await cdp.shot('9-state-window');
    await cdp.dump('9-state-window');
    return { whole: whole.body.total_samples, window: window_.body.total_samples };
  });

  // -------------------------------------------------------------- deleting
  await check('deleting asks first, and cancelling keeps the recording', async () => {
    await ensureDemo();
    const started = await api('/api/sessions/quick', {
      method: 'POST',
      body: JSON.stringify({ label: 'delete me', countdown_seconds: 0.2, voice: false }),
    });
    assert(started.status === 201, `session start returned ${started.status}`);

    let captured = 0;
    for (let i = 0; i < 60 && captured < 64; i += 1) {
      await sleep(100);
      const current = await api('/api/sessions/current');
      captured = current.body?.recording_state?.samples ?? 0;
    }
    assert(captured >= 64, `only ${captured} samples were captured`);
    const stopped = await api('/api/sessions/current/stop', { method: 'POST' });
    const path = stopped.body.summary.path;
    const id = path.split(/[\\/]/).pop();
    createdDatasets.push(path);

    await cdp.goto(`${BASE}/datasets/${id}`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('delete me')`, {
      label: 'the recording to appear',
    });

    const openDialog = async () => {
      await cdp.evaluate(`(() => {
        const button = document.querySelector('button[aria-label="Delete delete me"]');
        if (!button) throw new Error('no delete button on the row');
        button.click();
        return true;
      })()`);
      await cdp.waitFor(`document.querySelector('[role=dialog]') !== null`, {
        label: 'the confirmation dialog',
      });
    };

    await openDialog();
    const dialog = await cdp.evaluate(`(() => {
      const element = document.querySelector('[role=dialog]');
      return {
        text: element.innerText.toLowerCase(),
        focused: (document.activeElement?.innerText ?? '').trim(),
      };
    })()`);
    assert(dialog.text.includes('delete me'), 'the dialog does not name the recording');
    assert(
      dialog.text.includes('removes the whole dataset'),
      'the dialog does not say what will be removed',
    );
    assert(dialog.text.includes('delete for good'), 'the dialog has no confirm button');
    // A stray Enter must not be what deletes a dataset.
    assert(/cancel/i.test(dialog.focused), `focus starts on "${dialog.focused}", not Cancel`);
    await cdp.shot('10-delete-ask');
    await cdp.dump('10-delete-ask');

    await cdp.evaluate(`(() => {
      const button = [...document.querySelectorAll('[role=dialog] button')].find((candidate) =>
        candidate.innerText.trim().toLowerCase().startsWith('cancel'));
      button.click();
      return true;
    })()`);
    await sleep(500);
    const afterCancel = await api(`/api/recordings/${encodeURIComponent(id)}`);
    assert(afterCancel.status === 200, 'cancelling still deleted the recording');
    assert(
      (await cdp.evaluate(`document.querySelector('[role=dialog]') === null`)),
      'the dialog stayed open after cancelling',
    );

    await openDialog();
    await cdp.evaluate(`(() => {
      const button = [...document.querySelectorAll('[role=dialog] button')].find((candidate) =>
        candidate.innerText.trim().toLowerCase().startsWith('delete for good'));
      button.click();
      return true;
    })()`);

    let gone = false;
    for (let i = 0; i < 40 && !gone; i += 1) {
      await sleep(150);
      gone = (await api(`/api/recordings/${encodeURIComponent(id)}`)).status === 404;
    }
    assert(gone, 'confirming did not delete the recording');
    const listing = await api('/api/recordings');
    assert(
      !listing.body.recordings.some((item) => item.id === id),
      'the deleted recording is still listed',
    );
    await cdp.shot('11-delete-done');
    return { cancelledKept: true, deleted: id };
  });

  // ------------------------------------------------------------ housekeeping
  await check('stopping the source leaves the app idle, not broken', async () => {
    await api('/api/system/source', { method: 'POST', body: JSON.stringify({ mode: 'idle' }) });
    await cdp.goto(`${BASE}/`);
    await cdp.waitFor(`document.body.innerText.toLowerCase().includes('nothing is streaming')`, {
      label: 'the idle notice',
    });
    return { ok: true };
  });

  await check('the browser console stayed clean', () => {
    // A missing favicon is noise from the harness, not a defect in the app.
    const unique = [...new Set(consoleErrors.filter((message) => !/favicon/i.test(message)))];
    assert(unique.length === 0, `${unique.length} distinct console error(s):\n      ${unique.join('\n      ')}`);
    return { errors: 0 };
  });

  writeFileSync(
    join(OUT, 'report.json'),
    `${JSON.stringify({ base: BASE, results, consoleErrors: [...new Set(consoleErrors)] }, null, 2)}\n`,
  );
} finally {
  try {
    cdp?.socket.close();
  } catch {
    /* already gone */
  }
  chrome.kill();
  // Leave the API as we found it: no session, and the stream stopped.
  try {
    await api('/api/sessions/current/abort', { method: 'POST' });
    await api('/api/system/source', { method: 'POST', body: JSON.stringify({ mode: 'idle' }) });
  } catch {
    /* the server may already be gone */
  }
  // Remove the datasets this run wrote: the checks are on the app, not on the library.
  if (process.env.KEEP_DATASET !== '1') {
    for (const path of createdDatasets) rmSync(path, { recursive: true, force: true });
  }
}

const failed = results.filter((result) => !result.ok);
for (const result of results) {
  console.log(`${result.ok ? 'PASS' : 'FAIL'}  ${result.name}`);
  if (!result.ok) console.log(`      ${result.error}`);
}
console.log(`\n${results.length - failed.length}/${results.length} checks passed â€” screenshots in ${OUT}`);
process.exit(failed.length === 0 ? 0 : 1);
