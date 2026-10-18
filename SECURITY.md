# Security Policy

## Reporting a vulnerability

Please report vulnerabilities privately using GitHub's "Report a vulnerability" feature
(Security tab) rather than opening a public issue. Include reproduction steps and the
affected version. We aim to acknowledge reports within a few days.

## Security model

- By default the server binds to loopback (`127.0.0.1`) with no authentication.
- Set `SUPERTONIC_API_KEY` to require `Authorization: Bearer <key>` on all requests
  (WebSocket clients may also pass `?api_key=`).
- The server refuses to start when bound to a non-loopback host, or when
  `SUPERTONIC_PUBLIC_URL` is set (for example behind a tunnel), without an API key.
- If you expose the server through a tunnel or reverse proxy, always terminate TLS there
  and keep the API key secret; treat it like a password.
