#!/usr/bin/env node

import assert from 'node:assert/strict';

const baseUrl = (process.env.LOCKER_URL || '').replace(/\/$/, '');
if (!baseUrl) {
  throw new Error('LOCKER_URL is required; point this test at an isolated locker instance.');
}

async function request(path, body) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  let parsed;
  try {
    parsed = await response.json();
  } catch {
    parsed = null;
  }
  return { status: response.status, body: parsed };
}

const prefix = `phase0:characterization:${Date.now()}`;
const health = await fetch(`${baseUrl}/healthz`);
assert.equal(health.status, 200, 'healthz must answer 200');
assert.deepEqual(await health.json(), { ok: true });

const first = await request('/lock', {
  lock_key: `${prefix}:same`,
  lock_value: 'owner-a',
  ttl_ms: 5000,
});
assert.equal(first.status, 200);
assert.equal(first.body.acquired, true);

const contender = await request('/lock', {
  lock_key: `${prefix}:same`,
  lock_value: 'owner-b',
  ttl_ms: 5000,
});
assert.equal(contender.status, 200);
assert.equal(contender.body.acquired, false);

const ownerlessUnlock = await request('/unlock', { lock_key: `${prefix}:same` });
assert.equal(ownerlessUnlock.status, 200);
assert.equal(ownerlessUnlock.body.deleted, 1, 'current contract deletes without lock owner');

const ttlKey = `${prefix}:ttl`;
assert.equal((await request('/lock', {
  lock_key: ttlKey,
  lock_value: 'owner-ttl',
  ttl_ms: 250,
})).body.acquired, true);
await new Promise((resolve) => setTimeout(resolve, 450));
assert.equal((await request('/lock', {
  lock_key: ttlKey,
  lock_value: 'owner-after-ttl',
  ttl_ms: 5000,
})).body.acquired, true);

const raceKey = `${prefix}:race`;
const race = await Promise.all([
  request('/lock', { lock_key: raceKey, lock_value: 'race-a', ttl_ms: 5000 }),
  request('/lock', { lock_key: raceKey, lock_value: 'race-b', ttl_ms: 5000 }),
]);
assert.equal(race.filter((item) => item.body.acquired === true).length, 1);
assert.equal(race.filter((item) => item.body.acquired === false).length, 1);

const malformed = await request('/lock', { lock_key: '' });
assert.equal(malformed.status, 400);

console.log(JSON.stringify({
  test: 'redis-locker-characterization',
  result: 'PASS',
  observed: {
    health: '200/ok',
    same_key_contention: 'one acquired, one rejected',
    ownerless_unlock: 'active lock deleted with lock_key only',
    ttl_expiry: '250ms lock became acquirable after 450ms',
    concurrent_same_key: 'exactly one acquisition',
    malformed_payload: '400',
  },
}));
