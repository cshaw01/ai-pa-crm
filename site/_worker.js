// Workers + Static Assets entry.
//
// This site lives on Cloudflare's Workers + Static Assets model (the new
// unified flow), not legacy Pages, so the functions/ directory is NOT
// auto-detected as routes. We declare routes explicitly here and fall
// through to the static-asset binding for everything else.
//
// All AI-PA's CRM tenant subdomains stay on the existing FastAPI + Traefik
// stack — only chiefpa.com (apex) is served by this Worker.

import * as lead from './functions/api/lead.js';

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/lead') {
      const context = {
        request,
        env,
        params: {},
        waitUntil: (p) => ctx.waitUntil(p),
      };
      return lead.onRequest(context);
    }

    return env.ASSETS.fetch(request);
  },
};
