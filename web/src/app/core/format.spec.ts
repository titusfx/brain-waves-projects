import { describe, expect, it } from 'vitest';

import { bytes, clock, errorMessage, humanDuration, sourceLabel, statusTone } from './format';

describe('clock', () => {
  it('formats seconds as minutes and seconds', () => {
    expect(clock(0)).toBe('0:00');
    expect(clock(9)).toBe('0:09');
    expect(clock(95)).toBe('1:35');
    expect(clock(3600)).toBe('60:00');
  });

  it('says "unknown" rather than inventing a time', () => {
    // An open-ended state has no remaining time, and 0:00 would read as "finished".
    expect(clock(null)).toBe('—');
    expect(clock(undefined)).toBe('—');
    expect(clock(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('humanDuration', () => {
  it('scales the unit to the length', () => {
    expect(humanDuration(45)).toBe('45 s');
    expect(humanDuration(95)).toBe('1 m 35 s');
    expect(humanDuration(3725)).toBe('1 h 02 m');
  });
});

describe('bytes', () => {
  it('uses one decimal below ten units', () => {
    expect(bytes(512)).toBe('512 B');
    expect(bytes(2048)).toBe('2.0 kB');
    expect(bytes(15 * 1024)).toBe('15 kB');
  });
});

describe('statusTone', () => {
  it('treats only a genuine good contact as ok', () => {
    expect(statusTone('ok')).toBe('ok');
  });

  it('flags weak and strong contact as worth looking at, not as fine', () => {
    expect(statusTone('low')).toBe('warn');
    expect(statusTone('high')).toBe('warn');
  });

  it('treats dry, dead and saturated as bad', () => {
    expect(statusTone('DRY?')).toBe('bad');
    expect(statusTone('DEAD')).toBe('bad');
    expect(statusTone('artefact')).toBe('bad');
  });

  it('has a neutral tone for "no data yet"', () => {
    expect(statusTone(undefined)).toBe('idle');
    expect(statusTone('')).toBe('idle');
  });
});

describe('sourceLabel', () => {
  it('never lets the demo signal look like a headset', () => {
    expect(sourceLabel('live')).toBe('Dongle');
    expect(sourceLabel('demo')).toBe('Demo signal');
    expect(sourceLabel('idle')).toBe('Idle');
  });
});

describe('errorMessage', () => {
  it('prefers the API detail string', () => {
    expect(errorMessage({ error: { detail: 'Nothing is streaming.' } })).toBe(
      'Nothing is streaming.',
    );
  });

  it('joins FastAPI validation messages', () => {
    expect(
      errorMessage({ error: { detail: [{ msg: 'field required' }, { msg: 'too long' }] } }),
    ).toBe('field required; too long');
  });

  it('falls back to something a person can read', () => {
    expect(errorMessage(new Error(''))).toBe('Something went wrong.');
    expect(errorMessage(null)).toBe('Something went wrong.');
    expect(errorMessage('plain string')).toBe('plain string');
  });
});
