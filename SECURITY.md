# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly. Do **not** open a public issue.

1. Open a private [GitHub Security Advisory](https://github.com/AgriciDaniel/claude-seo/security/advisories/new) on this repository. Private vulnerability reporting is enabled, so the "Report a vulnerability" button on the Security tab opens the same form.
2. If the advisory form is unavailable to you, open a public issue titled "Security contact request" with no technical detail. The maintainer will reply with a private channel.
3. Encrypt sensitive disclosures if you can. Request the maintainer's PGP key in the advisory thread; the fingerprint is shared there on first request and rotated yearly.

When reporting, please include:

- A short description of the issue and the impact you believe it has.
- A minimal reproducer (URL, command line, payload, or short script).
- Affected versions and platforms.
- Whether you have a suggested fix.

## Coordinated disclosure

claude-seo follows a **90-day coordinated disclosure** policy.

| Day | Event |
|---:|---|
| 0  | Maintainer acknowledges receipt. |
| ≤ 3   | Initial triage: severity classification (CVSS v3.1) and reproducibility confirmation. |
| ≤ 14  | Mitigation or fix candidate proposed. |
| ≤ 30  | Fix released in a patch version or backport; reporter credited in the release notes (opt-out available). |
| ≤ 90  | Public advisory published if not earlier. |

If a fix cannot be shipped within 90 days, the maintainer will request an extension with a clear technical reason. The reporter retains the right to disclose at the 90-day mark.

## Supported versions

| Version line | Status | Notes |
|---|---|---|
| **2.x** | ✅ Fully supported | Active development; security and bug fixes. |
| **1.9.x** | ✅ Patch-only for security | Final 1.x line; only CVSS ≥ High issues backported. |
| < 1.9 | ❌ Unsupported | Please upgrade. |

## Threat model

claude-seo is a research and audit toolkit that runs on a user's workstation. It accepts user-supplied URLs and credentials, and issues HTTP requests against arbitrary internet hosts. The threat model has three primary attacker types:

1. **Malicious audit target.** A site the user points claude-seo at attempts to leak local-network or cloud-metadata data via SSRF chains: private IP literals, decimal/hex/octal IPv4, FQDN trailing dot, 30x redirects to private IPs, DNS rebinding (initial public resolution → later private), IPv4-mapped IPv6, dual-stack hosts with one private record.

   **Mitigation:** `scripts/url_safety.py` is the canonical pre-flight + DNS-pinned fetch layer. Every URL-fetching script in this repository validates through it: `validate_url_strict()` before opening a socket, then the `safe_requests_*` helpers, and `chromium_launch_args()` for Chromium. The parse-time `validate_url()` is reserved for URLs handed to a third-party API that fetches them. `google_auth.validate_url` is a deprecated alias, not a guard; `tests/test_url_safety_entrypoints.py` keeps repository code off it. See `tests/test_url_safety.py` for the regression suite (91 cases across 31 test functions, covering each bypass class).

2. **Tampered install.** A modified plugin install, GitHub release, or manual install script could deliver altered files. Plugin install is the default path; `curl ... | bash` is the legacy/manual path, so signature verification of release artifacts remains a defence-in-depth concern.

   **Mitigation status:** SHA-256 manifest tooling shipped in v2.0.0; install script verification is tracked for v2.3. Until install scripts verify manifests, users may install by cloning the tag explicitly and inspecting the diff against the previous release.

3. **Local privilege escalation against stored credentials.** The OAuth token at `~/.config/claude-seo/oauth-token.json` is the most sensitive on-disk artifact.

   **Mitigation:** v2 forces `0o600` on every write (`os.open` + `os.fchmod`) and remediates legacy `0o644` files in place on first load. Tokens never contain the OAuth `client_secret` — only the access/refresh pair plus expiry metadata.

## Known residual risks

- **Playwright + Chromium DNS rebinding, third-party hosts only.** Chromium does its own DNS resolution inside the renderer process, out of reach of claude-seo's Python-layer DNS pin (`url_safety._pin_dns`). Chromium is therefore launched with `url_safety.chromium_launch_args()`, a `--host-resolver-rules` entry that maps the audited host to the IP the pre-flight validated, so the main document and every same-host subresource connect to that address and a rebinding answer cannot redirect them. The pin is not applied when a trusted proxy resolves the target (see the next item). Hosts other than the audited one (third-party subresources, cross-host redirects) are still resolved by Chromium; the Playwright `route()` handler (`make_safe_playwright_route_handler`) re-validates each request and redirect hop (next item), but an attacker who controls such a host's DNS can still race Chromium's resolver after the handler's check. Mitigation: do not point `/seo` skills at untrusted sites with high-frequency redirects.
- **Browser redirect hops are refused after they are sent.** Playwright calls a `route()` handler for the first URL of a request only, never for the hops of a 30x redirect, so it cannot abort them. The rendering scripts register `page.on("request", handler.watch_request)`, which judges every hop by the route handler's own rule, and call `handler.check_redirects()` before returning anything: a hop to a refused target (a private address, a metadata endpoint, or another port on an allowlisted local host) fails the render with a `url_safety:` error and discards its content, accessibility tree, screenshot, and measurements. Chromium has already sent that hop's request when it is detected, so a blind request (a GET with no response returned to the caller) can still reach the refused target. Mitigation: the raw-HTTP path refuses the same redirects before connecting, and `render_page.py` fetches raw before it renders.
- **Unlighthouse (`/seo unlighthouse`), loopback and third-party hosts only.** Unlighthouse resolves DNS and follows redirects in its own processes, so `scripts/unlighthouse_run.py` carries the pre-flight pin into both. Chromium (Puppeteer, and every Lighthouse run, which attaches to the same browser) gets `chromium_launch_args()` through `puppeteerOptions.args`. Node (axios and got, which fetch robots.txt, sitemaps and every crawled route and keep its HTML in the report) preloads `scripts/node_net_guard.cjs` through `NODE_OPTIONS=--require`: the audited host resolves to the validated IP, and any connection to a non-public address is refused, including a redirect to an IP literal such as `169.254.169.254`. Unlighthouse's own route discovery is switched off: its crawler queued any link whose text contains the site URL, such as `https://site@10.0.0.1/`, and any subdomain, and Lighthouse loaded them in Chromium. The wrapper instead builds a URL list through `url_safety` from the site's sitemaps (or the target page's links), keeping only the target's exact scheme, host and port, and passes it as `urls`. Two gaps remain. Loopback stays reachable from Node, because Puppeteer and Lighthouse drive Chromium through its DevTools port on 127.0.0.1, so a crawled page can redirect the Node crawler to a loopback service. And Chromium has no per-request handler here, so third-party subresources and cross-host redirects are resolved and loaded by Chromium unchecked. Every run returns this in `warnings` and prints it to stderr. Neither pin is applied when a trusted proxy resolves the target. Mitigation: run `/seo unlighthouse` only against sites you trust, from a machine with no sensitive loopback services.
- **CONNECT proxies weaken DNS pinning.** Behind a configured HTTP proxy (`HTTPS_PROXY` and friends) the proxy resolves the final host itself, so `url_safety`'s pin degrades to the pre-flight check in `validate_url_strict`; the proxy host itself is exempted from the pinned scope only after passing the same hostname blocklist and `is_safe_ip` policy as an audit target, so a proxy on loopback, RFC 1918, RFC 6598, link-local, or a metadata address is refused rather than exempted.
- **IPv6-only audit targets.** The strict validator queries `family=AF_INET` for the initial resolution. Hosts with AAAA records only will surface as "DNS resolution failed". This is **fail-closed** by design — we'd rather refuse than connect to an unvalidated IPv6 endpoint. Tracked for a future patch (full dual-stack pinning, similar to the Playwright handler which already uses `AF_UNSPEC`).
- **Windows file permissions.** `os.fchmod(fd, 0o600)` is a no-op on Windows for non-ACL filesystems. Users on Windows should rely on per-user directory ACLs instead of POSIX mode bits. `scripts/backlinks_auth.py` additionally makes a best-effort `icacls <path> /inheritance:r /grant:r "%USERNAME%:F"` call after every write to (and load-time remediation of) `~/.config/claude-seo/backlinks-api.json`, restricting it to the current user on NTFS. This is best-effort only: a failure (missing `icacls`, a non-NTFS volume, a restricted shell) is logged as a warning and does not block the credential read or write, so on a failure the file's effective protection on Windows falls back to whatever the containing directory's ACLs already provide.

- **RFC 6598 (100.64.0.0/10) is refused by default.** Cloud providers serve instance metadata in this range, so `url_safety` treats it like RFC 1918. Tailscale also allocates from it, so a staging site reached over Tailscale is refused under the default policy. The escape hatch is `CLAUDE_SEO_LOCAL_TARGETS`, a comma-separated allowlist of `host` or `host:port` entries (for example `localhost:3000,127.0.0.1:8080,100.101.102.103`, the last being a Tailscale address). Its scope is deliberately narrow:
  - It is consulted **only** for the first, top-level URL passed to `validate_url` / `validate_url_strict`. Redirect targets and embedded subresources stay fail-closed, so a page served from an allowlisted dev server still cannot pull anything else off the local network.
  - Rendering through Playwright works for that top-level URL. The scripts pass it to `make_safe_playwright_route_handler(top_level_url=...)`, which reads the allowlist once and admits that exact origin (scheme, host, and port) up to the allowlist ceiling, so the page and its same-origin assets load. The same host on another port, another spelling of the same machine (`127.0.0.1` for `localhost`), any other loopback or private address, and redirects to any of them stay refused, in the route handler, in the redirect check, and in the raw path's DNS pin, which answers a non-public pin for the audited port only.
  - A host must be named exactly. There is no range, wildcard, or "allow private" mode, `host:port` matches that port only, and a bare `host` matches any port on that host.
  - Cloud metadata endpoints are refused even when listed, by name (`metadata.google.internal` and its siblings) and by address (169.254.169.254, `fd00:ec2::254`, and Alibaba's 100.100.100.200, which sits inside the Tailscale range). Link-local, multicast, unspecified, and reserved addresses are never allowlistable.
  - `is_safe_ip` is unchanged and reads no environment, so every fail-closed path downstream of the first connection is unaffected.
  - Unset, claude-seo behaves exactly as it did before the flag existed.

- **A loopback or private HTTP proxy is refused by default; `CLAUDE_SEO_TRUST_PROXY=1` is the opt-in.** Some sandboxes have no DNS resolver at all and route every outbound connection through an HTTP CONNECT proxy on loopback that applies the network policy (claude.ai cloud environments, locked-down CI runners, some corporate desktops). Under the default policy nothing leaves such a host: `validate_url_strict` cannot resolve the target, and since v2.3.0 a proxy on a non-public address is refused (#280). Setting `CLAUDE_SEO_TRUST_PROXY=1` declares that proxy the boundary. Its scope is deliberately narrow:
  - It applies only to a URL that `requests` would send through a configured proxy (`HTTPS_PROXY` and friends, honouring `NO_PROXY`, or an explicit `proxies=` mapping). A direct connection keeps the full resolve-and-pin policy, flag or no flag.
  - The proxy may sit on loopback, RFC 1918, or RFC 6598, up to the `CLAUDE_SEO_LOCAL_TARGETS` ceiling: a link-local, metadata, multicast, unspecified, or reserved proxy address, by literal or by resolution, is refused with or without the flag.
  - The target hostname is not resolved locally; the proxy resolves it. Scheme, authority-confusion, hostname-blocklist, and IP-literal checks still run before anything is sent, in `validate_url_strict` and in the Playwright route handler alike, so `http://169.254.169.254/`, `http://metadata.google.internal/`, and `http://10.0.0.5/` are refused exactly as before.
  - What moves to the proxy is the check that a *name* does not resolve to a private address. Set the flag only where the proxy enforces that itself; a bare `HTTPS_PROXY` pointing at an open relay is not such a proxy.
  - Unset, claude-seo behaves exactly as it did before the flag existed.

## Security-relevant code paths

If you are auditing, these are the high-leverage files:

| File | Purpose |
|---|---|
| `scripts/url_safety.py` | SSRF / DNS-rebinding canonical module. |
| `scripts/render_page.py` | Shared headless renderer (Playwright + trafilatura). |
| `scripts/fetch_page.py` | Raw-HTTP fetcher built on `url_safety.safe_requests_session`. |
| `scripts/capture_screenshot.py` | Playwright screenshot capture with resolver pin and safe route handler. |
| `scripts/unlighthouse_run.py` | Unlighthouse wrapper: Chromium resolver pin + Node net guard. |
| `scripts/node_net_guard.cjs` | Node preload that pins the audited host and refuses non-public connections. |
| `scripts/google_auth.py` | OAuth token lifecycle, `chmod 0o600` writes. Not an SSRF guard. |
| `scripts/backlinks_auth.py` | Backlink-API credential loading; SSRF guard via `url_safety`. |
| `tests/test_url_safety.py` | 91-case regression battery covering every bypass class. |

## What this policy does **not** cover

- Bugs that require attacker control of the user's machine (any local attacker is already game over).
- Vulnerabilities in upstream dependencies — please report those to their respective maintainers. We track CVEs in `requirements.txt` and bump pins under the `deps:` Dependabot stream.
- Quality-of-output issues (SEO recommendations, schema errors, etc.) — those are bugs, not security issues.

## Security-relevant practices

- No credentials or API keys are committed to this repository. `.gitignore` blocks every known credential filename pattern.
- Install scripts write only to user-level directories under `~/.claude/` and `~/.config/claude-seo/`.
- Python dependencies install into an isolated virtual environment. Plugin installs use persistent `CLAUDE_PLUGIN_DATA`; manual installs use `~/.claude/skills/seo/.venv/`. The runtime never falls back to global or user package installation.
- Every new fetcher must route through `scripts/url_safety.py` — there is no exception for "trusted" URLs.
