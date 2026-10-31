# Remote access and security

Supertonic listens only on your own computer (`127.0.0.1`) by default and needs no key
there. This page is for reaching it from somewhere else.

## Other computers on your network

Set `SUPERTONIC_HOST=0.0.0.0` (all interfaces) and an API key, for example in `.env`:

```bash
SUPERTONIC_HOST=0.0.0.0
SUPERTONIC_API_KEY=a-long-random-key
```

The server refuses to start on anything but loopback without an API key (exit status 2).
Clients on other machines then send `Authorization: Bearer <key>`. Your firewall may also
need to allow the port. Do this only on a network you trust; for the internet, use a tunnel
as below.

## Exposing the server with a Cloudflare Tunnel

Keep the server on loopback and let the tunnel connect to it; do not bind `0.0.0.0`.

```bash
export SUPERTONIC_API_KEY="$(openssl rand -hex 24)"
export SUPERTONIC_PUBLIC_URL="https://tts.example.com"   # your tunnel hostname
scripts/serve.sh                                         # still listens on 127.0.0.1:8787
cloudflared tunnel --url http://127.0.0.1:8787           # quick tunnel; or a named tunnel
```

Setting `SUPERTONIC_PUBLIC_URL` makes the API key mandatory: the server refuses to start
without it (exit status 2). A quick tunnel gets a random hostname, so set any value (for
example `SUPERTONIC_PUBLIC_URL=quick-tunnel`) just to turn the check on. As a second safety
net, a server without a key refuses every request that carries a proxy header
(`CF-Connecting-IP`, `X-Forwarded-For`, `Forwarded`, `X-Real-IP`) with
`403 forwarded_without_key`. Clients then send `Authorization: Bearer <key>`, and WebSocket
clients should use `wss://`. The web UI is served without a key but only does anything useful
once you enter the key.

## Web pages and a keyless server

A server without a key trusts every program on this machine, and a web page open in your
browser could otherwise reach it too (a cross-site form post needs no permission, and DNS
rebinding can even read the answers). So while no key is set the server also refuses:

- a request whose `Host` is not `localhost`, `127.0.0.1`, `[::1]`, the bind host or a name in
  `SUPERTONIC_ALLOWED_HOSTS`: `403 forbidden_host`;
- a browser request whose `Origin` is not the server's own (same scheme, host and port) or
  listed in `SUPERTONIC_ALLOWED_ORIGINS`: `403 forbidden_origin`.

The built-in web UI is same-origin and keeps working, and programs that send no `Origin`
(curl, SDKs, the MCP server) are unaffected. With an API key these checks are off: the key
protects the server, and tunnels and proxies with public host names keep working.
