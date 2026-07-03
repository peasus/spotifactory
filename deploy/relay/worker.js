/**
 * Spotifactory PKCE Auth Relay
 *
 * Routes:
 *   POST /register           — Pi registers {session_id, authorize_url}, stored for 10 min
 *   GET  /:session_id        — Redirects user's browser to the stored Spotify authorize URL
 *   GET  /callback           — Spotify posts code here; stores it keyed by state (session_id)
 *   GET  /poll/:session_id   — Pi polls until code is available, then receives it
 *
 * Requires a Workers KV namespace bound as SESSIONS.
 * Create with: wrangler kv namespace create SESSIONS
 * Then set the returned id in wrangler.toml.
 */

const SUCCESS_HTML = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Spotifactory</title>
  <style>
    body { font-family: sans-serif; text-align: center; padding: 60px 20px;
           background: #191414; color: #fff; }
    h1   { color: #1DB954; font-size: 2em; margin-bottom: 0.5em; }
    p    { color: #ccc; }
  </style>
</head>
<body>
  <h1>&#10003; Connected!</h1>
  <p>Your Spotifactory is ready.<br>You can close this tab.</p>
</body>
</html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname } = url;

    // ------------------------------------------------------------------
    // POST /register — Pi registers the PKCE authorize URL for this session
    // ------------------------------------------------------------------
    if (request.method === 'POST' && pathname === '/register') {
      let body;
      try {
        body = await request.json();
      } catch {
        return new Response('Bad Request', { status: 400 });
      }
      const { session_id, authorize_url } = body;
      if (!session_id || !authorize_url) {
        return new Response('Bad Request', { status: 400 });
      }
      await env.SESSIONS.put(
        session_id,
        JSON.stringify({ authorize_url, code: null }),
        { expirationTtl: 600 }
      );
      return new Response('OK', { status: 200 });
    }

    // ------------------------------------------------------------------
    // GET /callback — Spotify redirects here after user authorises
    // ------------------------------------------------------------------
    if (pathname === '/callback') {
      const code = url.searchParams.get('code');
      const state = url.searchParams.get('state');
      if (!code || !state) {
        return new Response('Bad Request', { status: 400 });
      }
      const stored = await env.SESSIONS.get(state, 'json');
      if (stored) {
        // Keep code available for 2 minutes — Pi should poll it up within seconds
        await env.SESSIONS.put(
          state,
          JSON.stringify({ ...stored, code }),
          { expirationTtl: 120 }
        );
      }
      return new Response(SUCCESS_HTML, {
        status: 200,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      });
    }

    // ------------------------------------------------------------------
    // GET /poll/:session_id — Pi polls until code is present
    // ------------------------------------------------------------------
    if (pathname.startsWith('/poll/')) {
      const session_id = pathname.slice(6);
      const stored = await env.SESSIONS.get(session_id, 'json');
      if (!stored || !stored.code) {
        return new Response('Not Found', { status: 404 });
      }
      return new Response(JSON.stringify({ code: stored.code }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // ------------------------------------------------------------------
    // GET /:session_id — User visits; redirect to Spotify authorize URL
    // ------------------------------------------------------------------
    if (pathname.length > 1) {
      const session_id = pathname.slice(1);
      const stored = await env.SESSIONS.get(session_id, 'json');
      if (!stored) {
        return new Response(
          'Session not found or expired. Please restart the setup on your device.',
          { status: 404 }
        );
      }
      return Response.redirect(stored.authorize_url, 302);
    }

    return new Response('Not Found', { status: 404 });
  },
};
