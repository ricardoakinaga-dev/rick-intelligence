import axios from 'axios';
import { config } from '../config';

export interface LockOperationResult {
    acquired?: boolean;
    deleted?: boolean;
    renewed?: boolean;
    error?: string;
}

export const acquireLock = async (
    key: string,
    value: string,
    ttl: number
): Promise<LockOperationResult & { acquired: boolean }> => {
    try {
        const response = await axios.post(`${config.REDIS_LOCKER_URL}/lock`, {
            lock_key: key,
            lock_value: value,
            ttl_ms: ttl,
        });
        return response.data;
    } catch (error) {
        console.error('Redis Lock Error');
        return { acquired: false, error: 'Lock service unreachable' };
    }
};

export const releaseLock = async (
    key: string,
    value: string
): Promise<LockOperationResult & { deleted: boolean }> => {
    try {
        const response = await axios.post(`${config.REDIS_LOCKER_URL}/unlock`, {
            lock_key: key,
            lock_value: value,
        });
        return response.data;
    } catch (error) {
        console.error('Redis Unlock Error');
        return { deleted: false, error: 'Lock service unreachable' };
    }
};

export const renewLock = async (
    key: string,
    value: string,
    ttl: number
): Promise<LockOperationResult & { renewed: boolean }> => {
    try {
        const response = await axios.post(`${config.REDIS_LOCKER_URL}/renew`, {
            lock_key: key,
            lock_value: value,
            ttl_ms: ttl,
        });
        return response.data;
    } catch (error) {
        console.error('Redis Renew Error');
        return { renewed: false, error: 'Lock service unreachable' };
    }
};
