import OpenAI from 'openai';
import { config } from '../config';

const openai = new OpenAI({
    apiKey: config.OPENAI_API_KEY,
});

const MAX_RETRIES = 3;
const INITIAL_DELAY = 1000;

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

async function withRetry<T>(fn: () => Promise<T>, operationName: string): Promise<T | null> {
    let attempt = 0;
    while (attempt < MAX_RETRIES) {
        try {
            return await fn();
        } catch (error: any) {
            attempt++;
            const isRateLimit = error?.status === 429;
            const isServerError = error?.status >= 500;

            if (!isRateLimit && !isServerError) {
                console.error(`[OpenAI] Fatal error in ${operationName}:`, error);
                return null; // Don't retry client errors
            }

            if (attempt >= MAX_RETRIES) {
                console.error(`[OpenAI] Max retries reached for ${operationName}:`, error);
                return null;
            }

            const delay = INITIAL_DELAY * Math.pow(2, attempt - 1); // 1s, 2s, 4s
            console.warn(`[OpenAI] Retrying ${operationName} (Attempt ${attempt}/${MAX_RETRIES}) in ${delay}ms...`);
            await sleep(delay);
        }
    }
    return null;
}

export const getEmbedding = async (text: string): Promise<number[]> => {
    return await withRetry(async () => {
        const response = await openai.embeddings.create({
            model: 'text-embedding-3-small',
            input: text,
        });
        return response.data[0].embedding;
    }, 'getEmbedding') || [];
};

export const chatCompletion = async (
    model: string,
    messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[],
    temperature = 0.2,
    responseFormat: OpenAI.Chat.Completions.ChatCompletionCreateParams['response_format'] = { type: 'text' }
): Promise<string | null> => {
    return await withRetry(async () => {
        const response = await openai.chat.completions.create({
            model,
            messages,
            temperature,
            response_format: responseFormat, // Important for JSON mode
        });
        return response.choices[0].message.content;
    }, 'chatCompletion');
};

export default openai;
