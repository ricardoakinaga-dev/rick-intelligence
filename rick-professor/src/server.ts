import Fastify from 'fastify';
import cors from '@fastify/cors';
import formbody from '@fastify/formbody';
import { config } from './config';
import webhookRoutes from './routes/webhook';
import openAiRoutes from './routes/openai';
import { redis } from './lib/redis';
import { checkQdrantHealth } from './lib/qdrant';

const server = Fastify({
    logger: {
        level: config.LOG_LEVEL,
        transport: config.NODE_ENV === 'development' ? { target: 'pino-pretty' } : undefined,
    },
});

server.register(cors);
server.register(formbody);
server.register(webhookRoutes);
server.register(openAiRoutes);

server.get('/healthz', async () => {
    const qdrantOk = await checkQdrantHealth();
    return {
        status: qdrantOk ? 'ok' : 'degraded',
        timestamp: new Date().toISOString(),
        service: 'rick-professor',
        qdrantOk,
    };
});

const gracefulShutdown = async (signal: string) => {
    server.log.info(`Recebido ${signal}. Iniciando encerramento seguro...`);

    try {
        await server.close();
        if (redis) {
            await redis.quit();
            server.log.info('Conexão Redis encerrada.');
        }
        server.log.info('Processo finalizado com sucesso.');
        process.exit(0);
    } catch (err) {
        server.log.error({ err }, 'Erro durante o encerramento');
        process.exit(1);
    }
};

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

const start = async () => {
    try {
        await server.listen({ port: config.PORT, host: '0.0.0.0' });
        server.log.info(`Rick Professor online na porta ${config.PORT}`);
    } catch (err) {
        server.log.error(err);
        process.exit(1);
    }
};

start();
