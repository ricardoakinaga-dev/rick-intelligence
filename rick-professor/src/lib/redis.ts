import Redis from 'ioredis';
import { config } from '../config';
import { log } from './logging';

export const redis = new Redis(config.REDIS_URL, {
    maxRetriesPerRequest: null, // Necessário para evitar falhas em streams/filas se houver desconexão prolongada
    enableReadyCheck: false,
    retryStrategy(times) {
        // Retry indefinido com backoff exponencial limitado a 5 segundos
        const delay = Math.min(times * 100, 5000);
        return delay;
    },
    reconnectOnError(err) {
        const targetError = 'READONLY';
        if (err.message.includes(targetError)) {
            // Reconnect on readonly error
            return true;
        }
        return false;
    },
});

redis.on('connect', () => {
    log('info', 'Redis conectado com sucesso', { url: config.REDIS_URL });
});

redis.on('error', (err) => {
    log('error', 'Erro na conexão com Redis', {
        error: err.message,
        stack: err.stack
    });
});

// Listener para reconexão
redis.on('reconnecting', () => {
    log('warn', 'Tentando reconectar ao Redis...');
});
