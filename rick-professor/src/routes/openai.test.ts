import assert from 'node:assert/strict';
import Fastify from 'fastify';
import test from 'node:test';
import openAiRoutes, { isApiKeyAuthorized } from './openai';

test('OpenAI-compatible auth fails closed when no API key is configured', () => {
    assert.equal(isApiKeyAuthorized(undefined, undefined), false);
    assert.equal(isApiKeyAuthorized('Bearer anything', undefined), false);
    assert.equal(isApiKeyAuthorized('Bearer ', ''), false);
});

test('OpenAI-compatible auth accepts only the configured bearer key', () => {
    assert.equal(isApiKeyAuthorized('Bearer test-only-openai-key', 'test-only-openai-key'), true);
    assert.equal(isApiKeyAuthorized('Bearer wrong-key', 'test-only-openai-key'), false);
    assert.equal(isApiKeyAuthorized('Basic test-only-openai-key', 'test-only-openai-key'), false);
});

test('OpenAI-compatible models route enforces the configured key', async () => {
    const app = Fastify({ logger: false });
    await app.register(openAiRoutes);
    await app.ready();

    const unauthorized = await app.inject({ method: 'GET', url: '/v1/models' });
    assert.equal(unauthorized.statusCode, 401);

    const authorized = await app.inject({
        method: 'GET',
        url: '/v1/models',
        headers: { authorization: 'Bearer test-only-openai-key' },
    });
    assert.equal(authorized.statusCode, 200);

    await app.close();
});
