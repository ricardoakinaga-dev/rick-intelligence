const express = require('express');
const Redis = require('ioredis');
const { z } = require('zod');

const PORT = process.env.PORT || 3000;

const maskRedisUrl = (value) => {
    try {
        const url = new URL(value);
        if (url.password) url.password = '***';
        if (url.username) url.username = '***';
        url.search = '';
        url.hash = '';
        return url.toString();
    } catch {
        return '<invalid redis url>';
    }
};

const createRedisClient = (redisUrl) => {
    const redis = new Redis(redisUrl, {
        // Retry strategy: keep retrying.
        retryStrategy: (times) => Math.min(times * 50, 2000),
    });

    redis.on('error', () => {
        console.error('Redis Client Error');
    });

    redis.on('connect', () => {
        console.log('Connected to Redis at ' + maskRedisUrl(redisUrl));
    });

    return redis;
};

// Zod Schemas
const lockSchema = z.object({
    lock_key: z.string().min(1),
    lock_value: z.string().min(1),
    ttl_ms: z.number().int().positive().default(45000),
});

const unlockSchema = z.object({
    lock_key: z.string().min(1),
    lock_value: z.string().min(1),
});

const renewSchema = z.object({
    lock_key: z.string().min(1),
    lock_value: z.string().min(1),
    ttl_ms: z.number().int().positive().default(45000),
});

const RELEASE_SCRIPT = `
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
`;

const RENEW_SCRIPT = `
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
`;

const invalidRequest = (res) => res.status(400).json({ ok: false, error: 'Invalid request' });

const createApp = (redis) => {
    const app = express();
    app.use(express.json());

// --- Endpoints ---

    // GET /healthz
    app.get('/healthz', async (req, res) => {
    try {
        const response = await redis.ping();
        if (response !== 'PONG') {
            throw new Error(`Unexpected Redis ping response: ${response}`);
        }
        return res.status(200).json({ ok: true });
    } catch (error) {
        console.error('Health check failed');
        return res.status(500).json({ ok: false, error: 'Redis unreachable' });
    }
    });

// POST /lock
    app.post('/lock', async (req, res) => {
    try {
        // Validate body
        const body = lockSchema.safeParse(req.body);
        if (!body.success) {
            return invalidRequest(res);
        }

        const { lock_key, lock_value, ttl_ms } = body.data;

        // SET key value NX PX ttl
        const result = await redis.set(lock_key, lock_value, 'NX', 'PX', ttl_ms);

        // result is 'OK' if set, or null if not set (already exists)
        const acquired = result === 'OK';

        return res.status(200).json({
            ok: true,
            acquired,
            result
        });

    } catch (error) {
        console.error('Lock error');
        return res.status(500).json({ ok: false, error: 'Lock service unavailable' });
    }
    });

// POST /unlock
    app.post('/unlock', async (req, res) => {
    try {
        // Validate body
        const body = unlockSchema.safeParse(req.body);
        if (!body.success) {
            return invalidRequest(res);
        }

        const { lock_key, lock_value } = body.data;

        const deletedCount = await redis.eval(RELEASE_SCRIPT, 1, lock_key, lock_value);

        return res.status(200).json({
            ok: true,
            deleted: deletedCount === 1,
        });

    } catch (error) {
        console.error('Unlock error');
        return res.status(500).json({ ok: false, error: 'Lock service unavailable' });
    }
    });

    app.post('/renew', async (req, res) => {
        try {
            const body = renewSchema.safeParse(req.body);
            if (!body.success) return invalidRequest(res);

            const { lock_key, lock_value, ttl_ms } = body.data;
            const renewed = await redis.eval(RENEW_SCRIPT, 1, lock_key, lock_value, ttl_ms);

            return res.status(200).json({
                ok: true,
                renewed: renewed === 1,
            });
        } catch (error) {
            console.error('Renew error');
            return res.status(500).json({ ok: false, error: 'Lock service unavailable' });
        }
    });

    app.use((error, req, res, next) => {
        console.error('Request parsing error');
        return res.status(400).json({ ok: false, error: 'Invalid request' });
    });

    return app;
};

const start = () => {
    const redisUrl = process.env.REDIS_URL;
    if (!redisUrl) {
        console.error('CRITICAL: REDIS_URL is not defined.');
        process.exit(1);
    }

    const redis = createRedisClient(redisUrl);
    const app = createApp(redis);
    return app.listen(PORT, () => {
        console.log(`redis-locker running on port ${PORT}`);
    });
};

if (require.main === module) start();

module.exports = {
    createApp,
    createRedisClient,
    RELEASE_SCRIPT,
    RENEW_SCRIPT,
};
