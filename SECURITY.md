# Security Policy

## Supported versions

Supertonic Server is young; security fixes go into the latest release only.

| Version | Supported |
|---|---|
| 0.1.x (latest) | Yes |
| Older | No |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Report it privately through
GitHub's private vulnerability reporting instead:

1. Open <https://github.com/saifulbabo67646/supertonic/security/advisories/new>
   (or the repository's **Security** tab, then **Report a vulnerability**).
2. Describe the problem, how to reproduce it, the version (`GET /v1/health` shows it) and
   your operating system.

We aim to acknowledge a report within 5 working days and to agree on a fix and a
disclosure date with you. We will credit you in the advisory unless you would rather not
be named.

## Security model

- By default the server binds to loopback (`127.0.0.1`) with no authentication.
- Set `SUPERTONIC_API_KEY` to require `Authorization: Bearer <key>` on all requests
  (WebSocket clients may also pass `?api_key=`).
- The server refuses to start when bound to a non-loopback host, or when
  `SUPERTONIC_PUBLIC_URL` is set (for example behind a tunnel), without an API key.
- Without an API key the server refuses requests that carry proxy headers, requests whose
  `Host` is not a loopback name (DNS rebinding) and browser requests from other origins
  (cross-site request forgery). `SUPERTONIC_ALLOWED_HOSTS` and `SUPERTONIC_ALLOWED_ORIGINS`
  widen these lists; with a key they do not apply.
- If you expose the server through a tunnel or reverse proxy, always terminate TLS there
  and keep the API key secret; treat it like a password.
