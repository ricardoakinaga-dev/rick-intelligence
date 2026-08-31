import Redis from 'ioredis';
import { config } from '../config';

const redis = new Redis(config.REDIS_URL, {
    maxRetriesPerRequest: 3,
    retryStrategy(times) {
        if (times > 3) return null;
        return Math.min(times * 50, 2000);
    },
});

redis.on('error', (err) => {
    console.error('[Redis Memory] Error:', err);
});

const MEMORY_TTL = 60 * 60 * 24; // 24 hours
const MAX_TURNS = 10; // 5 user + 5 assistant

export const getChatHistory = async (chatId: string): Promise<string> => {
    const key = `professor:memory:${chatId}`;
    try {
        // Get last N messages
        const raw = await redis.lrange(key, 0, MAX_TURNS - 1);
        // Messages are stored as "ROLE: CONTENT"
        // Redis pushes to head (LPUSH), so lrange returns [newest, ..., oldest]
        // We need to reverse them to be [oldest, ..., newest] for the prompt
        return raw.reverse().join('\n');
    } catch (error) {
        console.error(`[Redis Memory] Failed to get history for ${chatId}`, error);
        return "";
    }
};

export const addChatMessage = async (chatId: string, role: 'user' | 'assistant', content: string) => {
    const key = `professor:memory:${chatId}`;
    const entry = `${role.toUpperCase()}: ${content.replace(/\n/g, ' ')}`; // simple sanitization
    try {
        await redis.multi()
            .lpush(key, entry)
            .ltrim(key, 0, MAX_TURNS - 1)
            .expire(key, MEMORY_TTL)
            .exec();
    } catch (error) {
        console.error(`[Redis Memory] Failed to add message for ${chatId}`, error);
    }
};
