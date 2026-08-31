import { config } from '../config';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

const levels: Record<LogLevel, number> = {
    debug: 0,
    info: 1,
    warn: 2,
    error: 3,
};

const currentLevelValue = levels[config.LOG_LEVEL as LogLevel] || levels.info;

export const log = (level: LogLevel, message: string, meta?: any) => {
    const levelValue = levels[level];

    // Respeita o nível de log configurado
    if (levelValue < currentLevelValue) {
        return;
    }

    const logEntry = {
        timestamp: new Date().toISOString(),
        level,
        message,
        ...meta,
    };

    console.log(JSON.stringify(logEntry));
};
