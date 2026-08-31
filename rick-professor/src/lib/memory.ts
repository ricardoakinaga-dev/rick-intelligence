import { getRedis } from './redis';

const MEMORY_TTL = 60 * 60 * 24; // 24 hours
const MAX_TURNS = 10; // 5 user + 5 assistant

export const getChatHistory = async (chatId: string): Promise<string> => {
    const key = `professor:memory:${chatId}`;
    try {
        const redis = getRedis();
        // Get last N messages
        const raw = await redis.lrange(key, 0, MAX_TURNS - 1);
        // Messages are stored as "ROLE: CONTENT"
        // Redis pushes to head (LPUSH), so lrange returns [newest, ..., oldest]
        // We need to reverse them to be [oldest, ..., newest] for the prompt
        return raw.reverse().join('\n');
    } catch (error) {
        console.error(`[Redis Memory] Failed to get history for ${chatId}`);
        return "";
    }
};

export const addChatMessage = async (chatId: string, role: 'user' | 'assistant', content: string) => {
    const key = `professor:memory:${chatId}`;
    const entry = `${role.toUpperCase()}: ${content.replace(/\n/g, ' ')}`; // simple sanitization
    try {
        const redis = getRedis();
        await redis.multi()
            .lpush(key, entry)
            .ltrim(key, 0, MAX_TURNS - 1)
            .expire(key, MEMORY_TTL)
            .exec();
    } catch (error) {
        console.error(`[Redis Memory] Failed to add message for ${chatId}`);
    }
};
