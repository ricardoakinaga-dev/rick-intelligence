#!/usr/bin/env node

const baseUrl = process.env.LOCKER_URL || 'http://127.0.0.1:3317';

const request = async (path, options = {}) => {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: { 'content-type': 'application/json', ...(options.headers || {}) },
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { status: response.status, body };
};

const post = (path, body) => request(path, {
  method: 'POST',
  body: JSON.stringify(body),
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const main = async () => {
  const health = await request('/healthz');
  const owner = 'phase05-owner-a';
  const contender = 'phase05-owner-b';

  const first = await post('/lock', { lock_key: 'phase05:owner', lock_value: owner, ttl_ms: 2000 });
  const blocked = await post('/lock', { lock_key: 'phase05:owner', lock_value: contender, ttl_ms: 2000 });
  const wrongUnlock = await post('/unlock', { lock_key: 'phase05:owner', lock_value: contender });
  const wrongRenew = await post('/renew', { lock_key: 'phase05:owner', lock_value: contender, ttl_ms: 2000 });
  const renewed = await post('/renew', { lock_key: 'phase05:owner', lock_value: owner, ttl_ms: 2000 });
  const released = await post('/unlock', { lock_key: 'phase05:owner', lock_value: owner });
  const releasedAgain = await post('/unlock', { lock_key: 'phase05:owner', lock_value: owner });

  const expiryFirst = await post('/lock', { lock_key: 'phase05:expiry', lock_value: owner, ttl_ms: 120 });
  await sleep(250);
  const expirySecond = await post('/lock', { lock_key: 'phase05:expiry', lock_value: contender, ttl_ms: 1000 });
  await post('/unlock', { lock_key: 'phase05:expiry', lock_value: contender });

  const contentionKey = 'phase05:contention';
  const contention = await Promise.all(
    Array.from({ length: 16 }, (_, index) => post('/lock', {
      lock_key: contentionKey,
      lock_value: `phase05-contention-${index}`,
      ttl_ms: 2000,
    })),
  );
  const winners = contention.filter((item) => item.status === 200 && item.body?.acquired === true);
  const winner = contention.find((item) => item.status === 200 && item.body?.acquired === true);
  if (winner) {
    const winnerIndex = contention.indexOf(winner);
    await post('/unlock', { lock_key: contentionKey, lock_value: `phase05-contention-${winnerIndex}` });
  }

  const malformed = await post('/lock', { lock_key: '', lock_value: '', ttl_ms: -1 });
  const result = {
    status: 'PASS',
    health_ok: health.status === 200 && health.body?.ok === true,
    owner_acquisition: first.body?.acquired === true,
    contention_blocked: blocked.body?.acquired === false,
    wrong_owner_unlock_safe: wrongUnlock.body?.deleted === false,
    wrong_owner_renew_safe: wrongRenew.body?.renewed === false,
    owner_renewed: renewed.body?.renewed === true,
    owner_release: released.body?.deleted === true,
    repeated_release_safe: releasedAgain.body?.deleted === false,
    expiry_allows_new_owner: expiryFirst.body?.acquired === true && expirySecond.body?.acquired === true,
    concurrent_winner_count: winners.length,
    malformed_request_rejected: malformed.status === 400 && malformed.body?.error === 'Invalid request',
  };
  result.status = (
    result.health_ok
    && result.owner_acquisition
    && result.contention_blocked
    && result.wrong_owner_unlock_safe
    && result.wrong_owner_renew_safe
    && result.owner_renewed
    && result.owner_release
    && result.repeated_release_safe
    && result.expiry_allows_new_owner
    && result.concurrent_winner_count === 1
    && result.malformed_request_rejected
  ) ? 'PASS' : 'FAIL';
  console.log(JSON.stringify(result));
  process.exitCode = result.status === 'PASS' ? 0 : 1;
};

main().catch((error) => {
  console.error('locker e2e failed');
  process.exitCode = 1;
});
