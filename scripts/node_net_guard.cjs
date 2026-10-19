'use strict';
/**
 * SSRF / DNS-rebinding guard for third-party Node tools (unlighthouse).
 *
 * Preloaded with NODE_OPTIONS=--require by scripts/unlighthouse_run.py, so
 * it runs inside npx, unlighthouse and every Lighthouse worker it spawns.
 * Python's url_safety cannot reach those processes: they resolve DNS and
 * follow redirects on their own.
 *
 * - CLAUDE_SEO_PIN_HOST resolves to CLAUDE_SEO_PIN_IP, the address
 *   validate_url_strict() already checked, so a rebinding answer is never
 *   used for the audited host.
 * - Any other hostname that resolves to a non-public address is refused.
 * - A connection to a non-public IP literal is refused (redirects to
 *   http://169.254.169.254/ and friends).
 *
 * Loopback stays reachable as an IP literal or as "localhost": Puppeteer and
 * Lighthouse drive Chromium through its DevTools port on 127.0.0.1. The
 * pinned IP and the hosts in CLAUDE_SEO_NET_ALLOW (the configured proxies)
 * are always allowed.
 *
 * Inert unless CLAUDE_SEO_NET_GUARD=1.
 */

const dns = require('dns');
const net = require('net');

const BLOCKED_V4 = [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['169.254.0.0', 16],
  ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24],
  ['203.0.113.0', 24], ['224.0.0.0', 3],
];
const BLOCKED_V6 = [
  ['::', 128], ['100::', 64], ['2001::', 23], ['2001:db8::', 32],
  ['fc00::', 7], ['fe80::', 10], ['ff00::', 8],
];

function buildBlockList() {
  const list = new net.BlockList();
  for (const [addr, prefix] of BLOCKED_V4) list.addSubnet(addr, prefix, 'ipv4');
  for (const [addr, prefix] of BLOCKED_V6) list.addSubnet(addr, prefix, 'ipv6');
  return list;
}

function unwrapMapped(ip) {
  const match = /^::ffff:(\d+\.\d+\.\d+\.\d+)$/i.exec(ip);
  return match ? match[1] : ip;
}

function isLoopback(ip) {
  const addr = unwrapMapped(ip);
  return net.isIPv4(addr) ? addr.startsWith('127.') : addr === '::1';
}

function normalizeHost(host) {
  return String(host).toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
}

function install(env) {
  const pinHost = normalizeHost(env.CLAUDE_SEO_PIN_HOST || '');
  const pinIp = net.isIP(env.CLAUDE_SEO_PIN_IP || '') ? env.CLAUDE_SEO_PIN_IP : '';
  const allowed = new Set(
    (env.CLAUDE_SEO_NET_ALLOW || '').split(',').map(normalizeHost).filter(Boolean),
  );
  const blockList = buildBlockList();

  function isPublic(ip) {
    const addr = unwrapMapped(ip);
    const family = net.isIP(addr);
    if (!family) return false;
    return !isLoopback(addr) && !blockList.check(addr, family === 4 ? 'ipv4' : 'ipv6');
  }

  function refusal(host, ip) {
    const err = new Error(`claude-seo net guard: ${host} -> ${ip} is not a public address`);
    err.code = 'ECLAUDESEOBLOCKED';
    return err;
  }

  // An IP literal is judged on the spot: no resolver is involved.
  function literalAllowed(ip) {
    return ip === pinIp || allowed.has(normalizeHost(ip)) || isLoopback(ip) || isPublic(ip);
  }

  // A resolved hostname must be public everywhere; loopback only for "localhost".
  function resolvedAllowed(host, ip) {
    if (ip === pinIp || allowed.has(host)) return true;
    if (isLoopback(ip)) return host === 'localhost';
    return isPublic(ip);
  }

  const originalLookup = dns.lookup;

  function guardedLookup(hostname, options, callback) {
    if (typeof options === 'function') {
      callback = options;
      options = {};
    } else if (typeof options === 'number') {
      options = { family: options };
    }
    options = options || {};
    const host = normalizeHost(hostname);

    if (pinHost && pinIp && host === pinHost) {
      const family = net.isIP(pinIp);
      process.nextTick(() => {
        if (options.all) callback(null, [{ address: pinIp, family }]);
        else callback(null, pinIp, family);
      });
      return {};
    }

    // A literal "resolves" to itself (server.listen() passes one too), so it
    // gets the connection rule rather than the hostname rule.
    const allowedFor = net.isIP(host)
      ? (address) => literalAllowed(address)
      : (address) => resolvedAllowed(host, address);

    return originalLookup.call(dns, hostname, { ...options, all: true }, (err, addresses) => {
      if (err) return callback(err);
      const bad = addresses.find((entry) => !allowedFor(entry.address));
      if (bad) return callback(refusal(host, bad.address));
      if (options.all) return callback(null, addresses);
      if (!addresses.length) return callback(refusal(host, '(no address)'));
      return callback(null, addresses[0].address, addresses[0].family);
    });
  }

  dns.lookup = guardedLookup;
  dns.promises.lookup = (hostname, options) => new Promise((resolve, reject) => {
    guardedLookup(hostname, options || {}, (err, address, family) => {
      if (err) reject(err);
      else if (Array.isArray(address)) resolve(address);
      else resolve({ address, family });
    });
  });

  const originalConnect = net.Socket.prototype.connect;

  function connectHost(args) {
    const list = Array.isArray(args[0]) ? args[0] : args;
    const first = list[0];
    if (first && typeof first === 'object') return first.path ? null : first.host || 'localhost';
    if (typeof first === 'number' || /^\d+$/.test(String(first))) {
      return typeof list[1] === 'string' ? list[1] : 'localhost';
    }
    return null; // IPC path: no network.
  }

  net.Socket.prototype.connect = function guardedConnect(...args) {
    const host = connectHost(args);
    if (host !== null) {
      const addr = normalizeHost(host);
      if (net.isIP(addr) && !literalAllowed(addr)) {
        const err = refusal(addr, addr);
        process.nextTick(() => this.destroy(err));
        return this;
      }
    }
    return originalConnect.apply(this, args);
  };
}

if (process.env.CLAUDE_SEO_NET_GUARD === '1') {
  install(process.env);
}

module.exports = { install };
