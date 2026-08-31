import assert from 'node:assert/strict';
import Fastify from 'fastify';
import test from 'node:test';
import webhookRoutes, {
    isTelegramWebhookSecretValid,
    TelegramIdempotencyStore,
} from './webhook';

const update = {
    update_id: 9001,
    message: {
        message_id: 42,
        chat: { id: 123, type: 'private' },
        date: 1_700_000_000,
        text: 'pergunta clínica',
    },
};

test('Telegram webhook secret is fail-closed and constant-time compatible', () => {
    assert.equal(isTelegramWebhookSecretValid('test-only-telegram-secret', 'test-only-telegram-secret'), true);
    assert.equal(isTelegramWebhookSecretValid('wrong', 'test-only-telegram-secret'), false);
    assert.equal(isTelegramWebhookSecretValid('test-only-telegram-secret', undefined), false);
    assert.equal(isTelegramWebhookSecretValid(undefined, 'test-only-telegram-secret'), false);
});

test('Telegram webhook rejects unauthenticated requests and deduplicates update_id', async () => {
    const seen = new Set<string>();
    const store: TelegramIdempotencyStore = {
        async set(key, _value, _mode, _ttl, _condition) {
            if (seen.has(key)) return null;
            seen.add(key);
            return 'OK';
        },
    };
    let processed = 0;
    const app = Fastify({ logger: false });
    await app.register(webhookRoutes, {
        idempotencyStore: store,
        processMessage: async () => {
            processed += 1;
            return { ok: true, conversationId: 'test', mode: 'answer' };
        },
    });
    await app.ready();

    const health = await app.inject({ method: 'GET', url: '/health' });
    assert.equal(health.statusCode, 200);

    const missingSecret = await app.inject({ method: 'POST', url: '/webhook/telegram', payload: update });
    assert.equal(missingSecret.statusCode, 401);
    assert.equal(processed, 0);

    const first = await app.inject({
        method: 'POST',
        url: '/webhook/telegram',
        headers: { 'x-telegram-bot-api-secret-token': 'test-only-telegram-secret' },
        payload: update,
    });
    assert.equal(first.statusCode, 200);
    assert.deepEqual(first.json(), { received: true });

    const duplicate = await app.inject({
        method: 'POST',
        url: '/webhook/telegram',
        headers: { 'x-telegram-bot-api-secret-token': 'test-only-telegram-secret' },
        payload: update,
    });
    assert.equal(duplicate.statusCode, 200);
    assert.deepEqual(duplicate.json(), { received: true, duplicate: true });
    assert.equal(processed, 1);

    await app.close();
});

test('Telegram webhook fails closed when the idempotency store is unavailable', async () => {
    const app = Fastify({ logger: false });
    let processed = 0;
    const unavailableStore: TelegramIdempotencyStore = {
        async set() {
            throw new Error('redis unavailable');
        },
    };
    await app.register(webhookRoutes, {
        idempotencyStore: unavailableStore,
        processMessage: async () => {
            processed += 1;
            return { ok: true, conversationId: 'test', mode: 'answer' };
        },
    });
    await app.ready();

    const response = await app.inject({
        method: 'POST',
        url: '/webhook/telegram',
        headers: { 'x-telegram-bot-api-secret-token': 'test-only-telegram-secret' },
        payload: { ...update, update_id: 9002 },
    });
    assert.equal(response.statusCode, 503);
    assert.equal(processed, 0);

    await app.close();
});
