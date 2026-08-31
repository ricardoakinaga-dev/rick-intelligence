#!/usr/bin/env node

import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';

const baseUrl = (process.env.LOCKER_URL || '').replace(/\/$/, '');
if (!baseUrl) {
  throw new Error('LOCKER_URL is required; point this test at an isolated locker instance.');
}

const sampleCount = Number(process.env.SAMPLES || 20);
assert.equal(Number.isInteger(sampleCount) && sampleCount > 0, true);
const prefix = 'phase0:performance:' + Date.now();

const samples = await Promise.all(
  Array.from({ length: sampleCount }, async (_, index) => {
    const started = performance.now();
    const response = await fetch(baseUrl + '/lock', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        lock_key: prefix + ':' + index,
        lock_value: 'benchmark-' + index,
        ttl_ms: 10000,
      }),
    });
    const body = await response.json();
    assert.equal(response.status, 200);
    assert.equal(body.acquired, true);
    return Number((performance.now() - started).toFixed(3));
  }),
);

const sorted = [...samples].sort((a, b) => a - b);
const nearestObserved = (fraction) => sorted[Math.max(0, Math.ceil(fraction * sorted.length) - 1)];
const output = {
  test: 'locker-http-benchmark',
  result: 'PASS',
  n: samples.length,
  unit: 'ms',
  samples_ms: samples,
  p50: nearestObserved(0.5),
  p95: nearestObserved(0.95),
  min: sorted[0],
  max: sorted[sorted.length - 1],
  workload: 'unique keys, ttl_ms=10000, local Redis and HTTP loopback',
  limitation: 'local observation only; not a capacity test or production SLO',
};

console.log(JSON.stringify(output));
