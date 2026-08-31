import Redis from 'ioredis';
import { config } from '../config';
import { log } from './logging';

let redisClient: Redis | undefined;

const maskRedisUrl = (value: string): string => {
    try {
        const url = new URL(value);
        if (url.username) url.username = '***';
        if (url.password) url.password = '***';
        url.search = '';
        url.hash = '';
        return url.toString();
    } catch {
        return '<invalid redis url>';
    }
};

export const getRedis = (): Redis => {
    if (redisClient) return redisClient;

    redisClient = new Redis(config.REDIS_URL, {
        maxRetriesPerRequest: null, // Necessário para evitar falhas em streams/filas se houver desconexão prolongada
        enableReadyCheck: false,
        retryStrategy(times) {
            // Retry indefinido com backoff exponencial limitado a 5 segundos
            return Math.min(times * 100, 5000);
        },
        reconnectOnError(err) {
            return err.message.includes('READONLY');
        },
    });

    redisClient.on('connect', () => {
        log('info', 'Redis conectado com sucesso', { url: maskRedisUrl(config.REDIS_URL) });
    });

    redisClient.on('error', (err) => {
        log('error', 'Erro na conexão com Redis', { error: err.name || 'RedisError' });
    });

    redisClient.on('reconnecting', () => {
        log('warn', 'Tentando reconectar ao Redis...');
    });

    return redisClient;
};

export const closeRedis = async (): Promise<void> => {
    if (!redisClient) return;
    const client = redisClient;
    redisClient = undefined;
    await client.quit();
};
