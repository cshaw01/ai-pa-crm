// Cloudflare Pages Function — POST /api/lead
//
// Validates the demo form, verifies the Turnstile token, posts a notification
// to the admin Telegram chat, and returns the redirect URL the client should
// navigate to (industry-routed to the most relevant tenant subdomain).
//
// Required env vars (set in Pages project → Settings → Environment variables):
//   TURNSTILE_SECRET_KEY    server secret for Turnstile verification
//   TELEGRAM_BOT_TOKEN      bot token (BotFather) used to post lead notifications
//   TELEGRAM_CHAT_ID        numeric chat id where notifications land
//
// Industry → tenant subdomain mapping is the only thing that needs editing
// when a new tenant launches. Add a line and push.

const INDUSTRY_TO_REDIRECT = {
  hvac:           'https://hvac.chiefpa.com/',
  chiropractor:   'https://chiro.chiefpa.com/',
  insurance:      'https://insurance.chiefpa.com/',
  wellness:       'https://santhi.chiefpa.com/',
  spa:            'https://santhi.chiefpa.com/',
  salon:          'https://santhi.chiefpa.com/',
  beauty:         'https://santhi.chiefpa.com/',
  yoga:           'https://santhi.chiefpa.com/',
};

const FALLBACK_REDIRECT = '/thank-you';

const REVENUE_BANDS = ['lt-100k', '100k-500k', '500k-1m', '1m-plus', 'prefer-not-say'];

const MAX_BODY_BYTES = 4096;
const RATE_LIMIT_MAX = 10;
const RATE_LIMIT_WINDOW_SEC = 300;

// In-memory per-isolate rate limiter. Each Workers isolate has its own copy,
// so this is a soft limit, not a strict cap — good enough to deflect bots
// without adding KV. A determined attacker can still exceed by hitting many
// edge POPs; layered defence is Turnstile.
const rateMap = new Map();

export async function onRequestPost(context) {
  const { request, env } = context;
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';

  // Crude size guard. Defends against absurdly large payloads.
  const contentLength = Number(request.headers.get('content-length') || '0');
  if (contentLength > MAX_BODY_BYTES) return jsonError(413, 'payload_too_large');

  // Rate limit by IP.
  if (rateLimited(ip)) return jsonError(429, 'rate_limited');

  // Parse JSON body.
  let body;
  try {
    body = await request.json();
  } catch (_) {
    return jsonError(400, 'invalid_json');
  }
  if (!body || typeof body !== 'object') return jsonError(400, 'invalid_json');

  // Field validation.
  const errors = validate(body);
  if (Object.keys(errors).length) {
    return new Response(JSON.stringify({ ok: false, errors }), {
      status: 400,
      headers: { 'content-type': 'application/json' },
    });
  }

  // Turnstile verification.
  const tsOk = await verifyTurnstile(body.cf_turnstile_token, env.TURNSTILE_SECRET_KEY, ip);
  if (!tsOk) return jsonError(400, 'verification_failed');

  // Determine redirect from industry mapping.
  const industry = String(body.industry || '').toLowerCase().trim();
  const redirect = INDUSTRY_TO_REDIRECT[industry] || FALLBACK_REDIRECT;

  // Notify Telegram. Don't block the response on failure — losing the visitor
  // over a backend hiccup is worse than missing one notification, and CF Pages
  // logs preserve the request for recovery.
  context.waitUntil(notifyTelegram(env, body, request).catch((e) => {
    console.error('telegram notify failed', e && e.message ? e.message : e);
  }));

  return new Response(JSON.stringify({ ok: true, redirect }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

// Reject all non-POST methods cleanly.
export async function onRequest(context) {
  if (context.request.method !== 'POST') {
    return new Response(JSON.stringify({ ok: false, error: 'method_not_allowed' }), {
      status: 405,
      headers: { 'content-type': 'application/json', 'allow': 'POST' },
    });
  }
  return onRequestPost(context);
}

function validate(body) {
  const errors = {};

  const name = typeof body.name === 'string' ? body.name.trim() : '';
  if (!name) errors.name = 'Required';
  else if (name.length > 80) errors.name = 'Keep it under 80 characters';

  const email = typeof body.email === 'string' ? body.email.trim() : '';
  if (!email) errors.email = 'Required';
  else if (!isValidEmail(email)) errors.email = "That doesn't look like a valid email";

  const industry = typeof body.industry === 'string' ? body.industry.trim() : '';
  if (!industry) errors.industry = 'Pick one';
  else if (industry.length > 40) errors.industry = 'Pick one from the list';

  const revenue = typeof body.annual_revenue === 'string' ? body.annual_revenue.trim() : '';
  if (!revenue) errors.annual_revenue = 'Pick a range';
  else if (!REVENUE_BANDS.includes(revenue)) errors.annual_revenue = 'Pick a range';

  // Years is optional; only reject if present and bad.
  const yearsRaw = body.years_in_business;
  if (yearsRaw !== undefined && yearsRaw !== '' && yearsRaw !== null) {
    const yrs = Number(yearsRaw);
    if (!Number.isFinite(yrs) || yrs < 0 || yrs > 100) {
      errors.years_in_business = '0–100';
    }
  }

  return errors;
}

function isValidEmail(s) {
  if (typeof s !== 'string' || s.length > 200) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
}

async function verifyTurnstile(token, secret, ip) {
  if (!token || !secret) return false;
  try {
    const fd = new FormData();
    fd.append('secret', secret);
    fd.append('response', token);
    if (ip && ip !== 'unknown') fd.append('remoteip', ip);
    const res = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST',
      body: fd,
    });
    if (!res.ok) return false;
    const data = await res.json();
    return data && data.success === true;
  } catch (e) {
    console.error('turnstile error', e && e.message ? e.message : e);
    return false;
  }
}

async function notifyTelegram(env, body, request) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return;
  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  const country = request.headers.get('cf-ipcountry') || 'unknown';
  const ua = (request.headers.get('user-agent') || 'unknown').slice(0, 200);
  const referer = request.headers.get('referer') || '';

  const escape = (s) => String(s == null ? '' : s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);

  const lines = [
    '<b>🌱 New lead — chiefpa.com</b>',
    '',
    `<b>Name:</b> ${escape(body.name)}`,
    `<b>Email:</b> ${escape(body.email)}`,
    `<b>Industry:</b> ${escape(body.industry)}`,
    `<b>Years in business:</b> ${escape(body.years_in_business || '—')}`,
    `<b>Revenue band:</b> ${escape(body.annual_revenue)}`,
    '',
    `<i>From ${escape(ip)} (${escape(country)})</i>`,
    `<i>UA: ${escape(ua)}</i>`,
  ];
  if (referer) lines.push(`<i>Ref: ${escape(referer)}</i>`);

  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      chat_id: env.TELEGRAM_CHAT_ID,
      text: lines.join('\n'),
      parse_mode: 'HTML',
      disable_web_page_preview: true,
    }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error('telegram ' + res.status + ' ' + detail.slice(0, 200));
  }
}

function rateLimited(ip) {
  const now = Date.now();
  const windowMs = RATE_LIMIT_WINDOW_SEC * 1000;
  const entry = rateMap.get(ip) || { count: 0, since: now };
  if (now - entry.since > windowMs) {
    entry.count = 0;
    entry.since = now;
  }
  entry.count += 1;
  rateMap.set(ip, entry);
  return entry.count > RATE_LIMIT_MAX;
}

function jsonError(status, code) {
  return new Response(JSON.stringify({ ok: false, error: code }), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
