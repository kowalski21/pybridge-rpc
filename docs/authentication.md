# Authentication

PyBridge supports both bearer-token and cookie-based session auth. Pick the one that fits your client:

| Client | Recommended | Why |
|---|---|---|
| Your own browser app | **HttpOnly session cookie** | Immune to XSS exfiltration |
| Mobile / desktop app | Bearer token | No cookie jar, refresh tokens fit naturally |
| CLI / scripts / S2S | Bearer token | One curl flag |
| Third-party integrations | Bearer token (API key) | Standard, rotatable |

## Bearer tokens

The `headers` callback on `createClient` runs per request — updating your token source at runtime "just works":

```ts
let token: string | null = null;
export const api = createClient<AppRouter>("http://localhost:8000", {
  headers: async () => token ? { authorization: `Bearer ${token}` } : {},
});
export function setToken(t: string | null) { token = t; }
```

Read it on the Python side via a middleware:

```python
@bridge.middleware
async def auth(ctx, next_):
    token = ctx.headers.get("authorization", "").removeprefix("Bearer ")
    ctx.user = await verify_jwt(token)
    return await next_(ctx)
```

## Cookie sessions (HttpOnly + CSRF)

Two pieces, both ~one line:

**Server** — enable CORS for credentialed requests and double-submit-cookie CSRF:

```python
from pybridge.security import cors, csrf

app = bridge.asgi(middleware=[
    cors(origins=["http://localhost:5173"], credentials=True),
    csrf(cookie_name="pyb_csrf"),
])
```

`cors(credentials=True)` rejects `origins="*"` at construction time — browsers won't accept the combination, so failing fast prevents a confusing runtime bug.

**Client** — opt into credentialed `fetch` and tell the client where to read the CSRF cookie:

```ts
export const api = createClient<AppRouter>("http://localhost:8000", {
  credentials: "include",   // browser sends/receives cookies cross-origin
  csrfCookie: "pyb_csrf",   // value is echoed into X-CSRF-Token automatically
});
```

That's it — the runtime reads the cookie via `document.cookie` and adds the `X-CSRF-Token` header to every request. The Python middleware compares the cookie value to the header value with `secrets.compare_digest` and returns `403 CSRF_FAILED` on a mismatch.

The CSRF cookie is non-HttpOnly by necessity (JS has to read it to echo it back); the **session** cookie should stay HttpOnly — that's the one carrying the actual auth state. The CSRF cookie is harmless on its own.
