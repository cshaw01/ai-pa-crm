/**
 * WhatsApp sidecar — one per tenant.
 *
 * Talks to WhatsApp via Baileys (multi-device protocol, same mechanism as
 * WhatsApp Web). Exposes a small HTTP API used by the CRM FastAPI service
 * for connect / QR / status / disconnect / send. On inbound messages,
 * POSTs to the CRM webhook.
 *
 * Env:
 *   PORT              — listen port (default 3000)
 *   AUTH_DIR          — where to persist session creds (default /data/whatsapp)
 *   CRM_WEBHOOK_URL   — where to POST inbound messages
 *   WEBHOOK_SECRET    — shared secret sent in X-Webhook-Secret header
 *   TENANT_SLUG       — identifies this tenant in logs (optional)
 */

const express = require('express');
const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
    makeCacheableSignalKeyStore,
} = require('@whiskeysockets/baileys');
const qrcode = require('qrcode');
const pino = require('pino');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.PORT || '3000', 10);
const AUTH_DIR = process.env.AUTH_DIR || '/data/whatsapp';
const CRM_WEBHOOK_URL = process.env.CRM_WEBHOOK_URL || 'http://crm:8080/api/webhook/whatsapp';
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || '';
const TENANT = process.env.TENANT_SLUG || 'tenant';

const logger = pino({ level: process.env.LOG_LEVEL || 'warn' });

fs.mkdirSync(AUTH_DIR, { recursive: true });

// Connection state. 'disconnected' | 'connecting' | 'qr' | 'connected'
let sock = null;
let connectionState = 'disconnected';
let currentQRDataUrl = null;
let phoneNumber = null;
let lastError = null;
let reconnectTimer = null;

function log(...args) {
    console.log(`[${TENANT}]`, ...args);
}

// ---------- Baileys connection ----------

async function connectWhatsApp() {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (sock) {
        try { sock.ev.removeAllListeners(); } catch (e) {}
        try { sock.end(); } catch (e) {}
        sock = null;
    }

    connectionState = 'connecting';
    currentQRDataUrl = null;

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const { version } = await fetchLatestBaileysVersion();

    sock = makeWASocket({
        version,
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger),
        },
        logger,
        printQRInTerminal: false,
        browser: ['Chiefpa', 'Chrome', '1.0.0'],
        syncFullHistory: false,
        markOnlineOnConnect: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            try {
                currentQRDataUrl = await qrcode.toDataURL(qr, { width: 300, margin: 1 });
                connectionState = 'qr';
                log('QR generated');
            } catch (e) {
                log('QR encode failed:', e.message);
            }
        }

        if (connection === 'open') {
            connectionState = 'connected';
            currentQRDataUrl = null;
            phoneNumber = sock.user?.id?.split(':')[0]?.split('@')[0] || null;
            lastError = null;
            log('connected as', phoneNumber);
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const loggedOut = statusCode === DisconnectReason.loggedOut;
            log('connection closed. code=', statusCode, 'loggedOut=', loggedOut);

            if (loggedOut) {
                // Device unlinked from phone — purge creds so next /connect gets a fresh QR
                connectionState = 'disconnected';
                phoneNumber = null;
                currentQRDataUrl = null;
                try { clearAuthDir(); } catch (e) {}
            } else {
                // Transient — schedule a reconnect
                connectionState = 'connecting';
                reconnectTimer = setTimeout(() => {
                    connectWhatsApp().catch(err => {
                        lastError = err.message;
                        connectionState = 'disconnected';
                    });
                }, 3000);
            }
        }
    });

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const msg of messages) {
            if (msg.key.fromMe) continue;
            if (!msg.message) continue;
            if (msg.key.remoteJid?.endsWith('@g.us')) continue; // skip groups
            if (msg.key.remoteJid === 'status@broadcast') continue;

            const text = extractText(msg.message);
            if (!text) continue;

            const fromNumber = msg.key.remoteJid?.split('@')[0];
            if (!fromNumber) continue;

            const payload = {
                channel: 'whatsapp',
                identifier: '+' + fromNumber,
                identifier_type: 'whatsapp',
                sender_name: msg.pushName || '',
                text,
                timestamp: msg.messageTimestamp,
                raw_id: msg.key.id,
            };

            try {
                await postToWebhook(payload);
            } catch (e) {
                log('webhook delivery failed:', e.message);
            }
        }
    });
}

function extractText(message) {
    if (!message) return null;
    if (message.conversation) return message.conversation;
    if (message.extendedTextMessage?.text) return message.extendedTextMessage.text;
    if (message.imageMessage?.caption) return '[image] ' + (message.imageMessage.caption || '');
    if (message.videoMessage?.caption) return '[video] ' + (message.videoMessage.caption || '');
    if (message.documentMessage) {
        return '[document] ' + (message.documentMessage.caption || message.documentMessage.fileName || '');
    }
    if (message.audioMessage) return '[voice note]';
    if (message.locationMessage) {
        const { degreesLatitude, degreesLongitude } = message.locationMessage;
        return `[location] ${degreesLatitude},${degreesLongitude}`;
    }
    return null;
}

async function postToWebhook(payload) {
    const resp = await fetch(CRM_WEBHOOK_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Webhook-Secret': WEBHOOK_SECRET,
        },
        body: JSON.stringify(payload),
    });
    if (!resp.ok) {
        throw new Error(`webhook ${resp.status}: ${await resp.text()}`);
    }
}

// ---------- HTTP API ----------

const app = express();
app.use(express.json({ limit: '1mb' }));

app.get('/status', (req, res) => {
    res.json({
        state: connectionState,
        phone: phoneNumber,
        has_qr: !!currentQRDataUrl,
        error: lastError,
    });
});

app.get('/qr', (req, res) => {
    res.json({
        state: connectionState,
        qr_data_url: currentQRDataUrl,
        phone: phoneNumber,
    });
});

app.post('/connect', async (req, res) => {
    if (connectionState === 'connected') {
        return res.json({ status: 'already_connected', phone: phoneNumber });
    }
    if (connectionState === 'connecting' || connectionState === 'qr') {
        return res.json({ status: 'in_progress', state: connectionState });
    }
    lastError = null;
    connectWhatsApp().catch(err => {
        lastError = err.message;
        connectionState = 'disconnected';
        log('connect failed:', err.message);
    });
    res.json({ status: 'starting' });
});

app.post('/disconnect', async (req, res) => {
    try {
        if (sock) {
            try { await sock.logout(); } catch (e) {}
            try { sock.end(); } catch (e) {}
            sock = null;
        }
        clearAuthDir();
        connectionState = 'disconnected';
        phoneNumber = null;
        currentQRDataUrl = null;
        res.json({ status: 'disconnected' });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.post('/send', async (req, res) => {
    try {
        if (!sock || connectionState !== 'connected') {
            return res.status(400).json({ error: 'not_connected', state: connectionState });
        }
        const { to, text } = req.body || {};
        if (!to || !text) {
            return res.status(400).json({ error: 'to and text required' });
        }
        const jid = toJid(to);
        const result = await sock.sendMessage(jid, { text });
        res.json({ status: 'sent', id: result.key.id, jid });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Empty AUTH_DIR contents without removing the mount point itself
function clearAuthDir() {
    if (!fs.existsSync(AUTH_DIR)) {
        fs.mkdirSync(AUTH_DIR, { recursive: true });
        return;
    }
    for (const entry of fs.readdirSync(AUTH_DIR)) {
        fs.rmSync(path.join(AUTH_DIR, entry), { recursive: true, force: true });
    }
}

function toJid(phoneOrJid) {
    if (phoneOrJid.includes('@')) return phoneOrJid;
    const clean = phoneOrJid.replace(/[^0-9]/g, '');
    return clean + '@s.whatsapp.net';
}

// ---------- startup ----------

(async () => {
    // If we already have persisted creds, auto-reconnect on boot
    const credsPath = path.join(AUTH_DIR, 'creds.json');
    if (fs.existsSync(credsPath)) {
        log('existing creds found, reconnecting...');
        connectWhatsApp().catch(err => {
            lastError = err.message;
            connectionState = 'disconnected';
            log('auto-reconnect failed:', err.message);
        });
    }

    app.listen(PORT, '0.0.0.0', () => {
        log(`sidecar listening on :${PORT}`);
    });
})();
