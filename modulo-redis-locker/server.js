const express = require('express');
const Redis = require('ioredis');
const { z } = require('zod');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const REDIS_URL = process.env.REDIS_URL;

if (!REDIS_URL) {
    console.error("CRITICAL: REDIS_URL is not defined.");
    process.exit(1);
}

const redis = new Redis(REDIS_URL, {
    // Retry strategy: keep retrying.
    retryStrategy: (times) => Math.min(times * 50, 2000),
});

redis.on('error', (err) => {
    console.error('Redis Client Error:', err);
});

redis.on('connect', () => {
    // Mask password in logs just in case
    const maskedUrl = REDIS_URL.replace(/:[^:]*@/, ':***@');
    console.log('Connected to Redis at ' + maskedUrl);
});

// Zod Schemas
const lockSchema = z.object({
    lock_key: z.string().min(1),
    lock_value: z.string().min(1),
    ttl_ms: z.number().int().positive().default(45000),
});

const unlockSchema = z.object({
    lock_key: z.string().min(1),
});

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
        console.error('Health check failed:', error);
        return res.status(500).json({ ok: false, error: 'Redis unreachable' });
    }
});

// POST /lock
app.post('/lock', async (req, res) => {
    try {
        // Validate body
        const body = lockSchema.safeParse(req.body);
        if (!body.success) {
            return res.status(400).json({ ok: false, error: body.error.format() });
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
        console.error('Lock error:', error);
        return res.status(500).json({ ok: false, error: error.message });
    }
});

// POST /unlock
app.post('/unlock', async (req, res) => {
    try {
        // Validate body
        const body = unlockSchema.safeParse(req.body);
        if (!body.success) {
            return res.status(400).json({ ok: false, error: body.error.format() });
        }

        const { lock_key } = body.data;

        // DEL key
        const deletedCount = await redis.del(lock_key);

        return res.status(200).json({
            ok: true,
            deleted: deletedCount // 1 if deleted, 0 if not found
        });

    } catch (error) {
        console.error('Unlock error:', error);
        return res.status(500).json({ ok: false, error: error.message });
    }
});

app.listen(PORT, () => {
    console.log(`redis-locker running on port ${PORT}`);
});
