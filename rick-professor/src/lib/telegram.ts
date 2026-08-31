import axios from 'axios';
import { config } from '../config';

const TELEGRAM_API_URL = `https://api.telegram.org/bot${config.TELEGRAM_BOT_TOKEN}`;

export const sendMessage = async (chatId: string, text: string) => {
    if (!config.TELEGRAM_BOT_TOKEN) {
        console.warn('TELEGRAM_BOT_TOKEN not set, skipping message send.');
        return;
    }

    try {
        // Basic splitting logic (simplified from n8n node 17)
        const MAX_LENGTH = 3800;
        const parts = [];
        let remaining = text;

        while (remaining.length > 0) {
            if (remaining.length <= MAX_LENGTH) {
                parts.push(remaining);
                break;
            }

            let cutIndex = remaining.lastIndexOf('\n', MAX_LENGTH);
            if (cutIndex === -1) cutIndex = MAX_LENGTH;

            parts.push(remaining.slice(0, cutIndex));
            remaining = remaining.slice(cutIndex).trim();
        }

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            const finalCheck = parts.length > 1 ? `(${i + 1}/${parts.length})\n${part}` : part;

            await axios.post(`${TELEGRAM_API_URL}/sendMessage`, {
                chat_id: chatId,
                text: finalCheck,
                disable_web_page_preview: true,
            });
        }

    } catch (error) {
        console.error('Telegram Send Error:', error);
    }
};
