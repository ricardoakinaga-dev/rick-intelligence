const assert = require('node:assert/strict');
const test = require('node:test');
const http = require('node:http');
const { createApp, RELEASE_SCRIPT, RENEW_SCRIPT } = require('../server');

class FakeRedis {
    constructor() {
        this.values = new Map();
        this.evalCalls = [];
    }

    async ping() {
        return 'PONG';
    }

    async set(key, value) {
        if (this.values.has(key)) return null;
        this.values.set(key, value);
        return 'OK';
    }

    async eval(script, keyCount, key, value, ttl) {
        this.evalCalls.push({ script, keyCount, key, value, ttl });
        if (script === RELEASE_SCRIPT) {
            if (this.values.get(key) !== value) return 0;
            this.values.delete(key);
            return 1;
        }
        if (script === RENEW_SCRIPT) {
            return this.values.get(key) === value ? 1 : 0;
        }
        throw new Error('unexpected script');
    }
}

async function withServer(redis, callback) {
    const server = http.createServer(createApp(redis));
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const { port } = server.address();
    try {
        return await callback(`http://127.0.0.1:${port}`);
    } finally {
        await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
}

test('lock remains compatible and unlock is owner-safe compare-delete', async () => {
    const redis = new FakeRedis();
    await withServer(redis, async (baseUrl) => {
        const acquired = await fetch(`${baseUrl}/lock`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k', lock_value: 'owner-a', ttl_ms: 45000 }),
        });
        assert.deepEqual(await acquired.json(), { ok: true, acquired: true, result: 'OK' });

        const wrong = await fetch(`${baseUrl}/unlock`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k', lock_value: 'owner-b' }),
        });
        assert.deepEqual(await wrong.json(), { ok: true, deleted: false });
        assert.equal(redis.values.get('k'), 'owner-a');

        const correct = await fetch(`${baseUrl}/unlock`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k', lock_value: 'owner-a' }),
        });
        assert.deepEqual(await correct.json(), { ok: true, deleted: true });
        assert.equal(redis.values.has('k'), false);
        assert.equal(redis.evalCalls[0].script, RELEASE_SCRIPT);
    });
});

test('renew is owner-safe and unlock requires a value', async () => {
    const redis = new FakeRedis();
    await withServer(redis, async (baseUrl) => {
        redis.values.set('k', 'owner-a');

        const invalid = await fetch(`${baseUrl}/unlock`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k' }),
        });
        assert.equal(invalid.status, 400);
        assert.deepEqual(await invalid.json(), { ok: false, error: 'Invalid request' });

        const wrong = await fetch(`${baseUrl}/renew`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k', lock_value: 'owner-b', ttl_ms: 5000 }),
        });
        assert.deepEqual(await wrong.json(), { ok: true, renewed: false });

        const correct = await fetch(`${baseUrl}/renew`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lock_key: 'k', lock_value: 'owner-a', ttl_ms: 5000 }),
        });
        assert.deepEqual(await correct.json(), { ok: true, renewed: true });
        assert.equal(redis.evalCalls.at(-1).script, RENEW_SCRIPT);
    });
});
