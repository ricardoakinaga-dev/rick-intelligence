import axios from 'axios';
import { config } from '../config';

export const acquireLock = async (
    key: string,
    value: string,
    ttl: number
): Promise<{ acquired: boolean; error?: string }> => {
    try {
        const response = await axios.post(`${config.REDIS_LOCKER_URL}/lock`, {
            lock_key: key,
            lock_value: value,
            ttl_ms: ttl,
        });
        return response.data;
    } catch (error) {
        console.error('Redis Lock Error:', error);
        return { acquired: false, error: 'Lock service unreachable' };
    }
};
