'use strict';
/**
 * SSRF / DNS-rebinding guard for third-party Node tools (unlighthouse).
 *
 * Preloaded with NODE_OPTIONS=--require by scripts/unlighthouse_run.py, so
 * it runs inside npx, unlighthouse and every Lighthouse worker it spawns.
 * Python's url_safety cannot reach those processes: they resolve DNS and
 * follow redirects on their own.
 *
 * Every TCP connection is judged on its address AND port:
 *
 * - CLAUDE_SEO_PIN_HOST resolves to CLAUDE_SEO_PIN_IP, the address
 *   validate_url_strict() already checked, so a rebinding answer is never
 *   used for the audited host. A non-public pin exists only because
 *   CLAUDE_SEO_LOCAL_TARGETS named that origin, so it is reachable on
 *   CLAUDE_SEO_PIN_PORT only.
 * - Any other non-public address is refused, by hostname or by IP literal
 *   (redirects to http://169.254.169.254/ and friends).
 * - Loopback is refused too, except Chromium's DevTools ports, which
 *   Puppeteer and Lighthouse need: this process learns each one from the
 *   "DevTools listening on ws://127.0.0.1:PORT/" line of a Chromium it
 *   spawns, and a Lighthouse worker from its --port=PORT argument. A
 *   crawled page cannot redirect the crawler to any other local service.
 * - The host:port pairs in CLAUDE_SEO_NET_ALLOW (the configured proxies)
 *   are allowed, on that port only.
 *
 * Inert unless CLAUDE_SEO_NET_GUARD=1.
 */

const childProcess = require('child_process');
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
const DEVTOOLS_LINE = /DevTools listening on ws:\/\/[^/\s]*:(\d+)\//g;

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

function install(env, argv = process.argv) {
  const pinHost = normalizeHost(env.CLAUDE_SEO_PIN_HOST || '');
  const pinIp = net.isIP(env.CLAUDE_SEO_PIN_IP || '') ? env.CLAUDE_SEO_PIN_IP : '';
  const pinPort = Number(env.CLAUDE_SEO_PIN_PORT) || 0;
  // "host:port" entries; the host alone only matters for a bare lookup.
  const allowed = new Set();
  const allowedHosts = new Set();
  for (const entry of (env.CLAUDE_SEO_NET_ALLOW || '').split(',')) {
    const match = /^(.*):(\d+)$/.exec(entry.trim());
    if (!match) continue;
    const host = normalizeHost(match[1]);
    allowed.add(`${host}:${Number(match[2])}`);
    allowedHosts.add(host);
  }
  const blockList = buildBlockList();

  // Chromium's DevTools ports, the only loopback ports this process may use.
  const devtoolsPorts = new Set();
  for (const arg of argv) {
    const match = /^--port=(\d+)$/.exec(arg);
    if (match) devtoolsPorts.add(Number(match[1]));
  }

  function isPublic(ip) {
    const addr = unwrapMapped(ip);
    const family = net.isIP(addr);
    if (!family) return false;
    return !isLoopback(addr) && !blockList.check(addr, family === 4 ? 'ipv4' : 'ipv6');
  }

  function refusal(host, ip, port) {
    const where = port ? `${ip}:${port}` : ip;
    const err = new Error(`claude-seo net guard: ${host} -> ${where} is not a public address`);
    err.code = 'ECLAUDESEOBLOCKED';
    return err;
  }

  // The one rule for a connection: `host` is the name asked for (or the
  // literal itself), `ip` where it lands, `port` the TCP port.
  function connectionAllowed(host, ip, port) {
    if (allowed.has(`${host}:${port}`) || allowed.has(`${normalizeHost(ip)}:${port}`)) return true;
    if (pinIp && ip === pinIp && (isPublic(pinIp) || port === pinPort)) return true;
    if (isLoopback(ip)) return devtoolsPorts.has(port);
    return isPublic(ip);
  }

  // Without a port (a bare dns.lookup), refuse only what no port could make
  // acceptable; the connection itself is judged again with its port.
  function resolutionAllowed(host, ip) {
    if (allowedHosts.has(host) || ip === pinIp) return true;
    return isLoopback(ip) || isPublic(ip);
  }

  const originalLookup = dns.lookup;

  function lookupWith(check, hostname, options, callback) {
    if (typeof options === 'function') {
      callback = options;
      options = {};
    } else if (typeof options === 'number') {
      options = { family: options };
    }
    options = options || {};
    const host = normalizeHost(hostname);

    const reply = (addresses) => {
      if (options.all) return callback(null, addresses);
      return callback(null, addresses[0].address, addresses[0].family);
    };

    if (pinHost && pinIp && host === pinHost) {
      const entry = { address: pinIp, family: net.isIP(pinIp) };
      if (!check(host, pinIp)) {
        process.nextTick(() => callback(refusal(host, pinIp)));
        return {};
      }
      process.nextTick(() => reply([entry]));
      return {};
    }

    return originalLookup.call(dns, hostname, { ...options, all: true }, (err, addresses) => {
      if (err) return callback(err);
      if (!addresses.length) return callback(refusal(host, '(no address)'));
      const bad = addresses.find((entry) => !check(host, entry.address));
      if (bad) return callback(refusal(host, bad.address));
      return reply(addresses);
    });
  }

  function guardedLookup(hostname, options, callback) {
    return lookupWith(resolutionAllowed, hostname, options, callback);
  }

  dns.lookup = guardedLookup;
  dns.promises.lookup = (hostname, options) => new Promise((resolve, reject) => {
    guardedLookup(hostname, options || {}, (err, address, family) => {
      if (err) reject(err);
      else if (Array.isArray(address)) resolve(address);
      else resolve({ address, family });
    });
  });

  // Learn the DevTools port of every Chromium this process starts. emit() is
  // wrapped rather than a 'data' listener added, so the stream's flowing
  // mode, and Puppeteer's own reading of that line, are left untouched.
  const originalSpawn = childProcess.spawn;
  childProcess.spawn = function guardedSpawn(...args) {
    const child = originalSpawn.apply(this, args);
    const stderr = child && child.stderr;
    if (stderr && typeof stderr.emit === 'function') {
      let tail = '';
      const originalEmit = stderr.emit;
      stderr.emit = function sniff(event, chunk, ...rest) {
        if (event === 'data' && chunk != null) {
          tail = (tail + String(chunk)).slice(-4096);
          for (const match of tail.matchAll(DEVTOOLS_LINE)) devtoolsPorts.add(Number(match[1]));
        }
        return originalEmit.call(this, event, chunk, ...rest);
      };
    }
    return child;
  };

  const originalConnect = net.Socket.prototype.connect;

  // net.connect() passes [options, cb] marked internally; a direct
  // socket.connect() call may pass (options[, cb]) or (port[, host][, cb]).
  function connectOptions(args) {
    if (Array.isArray(args[0])) return { options: args[0][0], args };
    if (args[0] && typeof args[0] === 'object') return { options: args[0], args };
    if (typeof args[0] === 'number' || /^\d+$/.test(String(args[0]))) {
      const options = { port: Number(args[0]) };
      if (typeof args[1] === 'string') options.host = args[1];
      const callback = args.find((arg) => typeof arg === 'function');
      return { options, args: callback ? [options, callback] : [options] };
    }
    return { options: null, args }; // IPC path: no network.
  }

  net.Socket.prototype.connect = function guardedConnect(...rawArgs) {
    const { options, args } = connectOptions(rawArgs);
    if (!options || options.path) return originalConnect.apply(this, args);

    const host = normalizeHost(options.host || 'localhost');
    const port = Number(options.port) || 0;

    if (net.isIP(host)) {
      if (!connectionAllowed(host, host, port)) {
        const err = refusal(host, host, port);
        process.nextTick(() => this.destroy(err));
        return this;
      }
      return originalConnect.apply(this, args);
    }

    // A hostname: judge every address it resolves to with this port.
    const innerLookup = typeof options.lookup === 'function' ? options.lookup : null;
    options.lookup = (name, lookupOptions, callback) => {
      if (innerLookup) {
        return innerLookup(name, lookupOptions, (err, address, family) => {
          if (err) return callback(err);
          const list = Array.isArray(address) ? address : [{ address, family }];
          const bad = list.find((entry) => !connectionAllowed(host, entry.address, port));
          if (bad) return callback(refusal(host, bad.address, port));
          return callback(null, address, family);
        });
      }
      return lookupWith(
        (name2, ip) => connectionAllowed(name2, ip, port), name, lookupOptions, callback,
      );
    };
    return originalConnect.apply(this, args);
  };

  // ESM `import { spawn } from 'child_process'` reads a snapshot; refresh it.
  require('module').syncBuiltinESMExports();

  return { devtoolsPorts };
}

if (process.env.CLAUDE_SEO_NET_GUARD === '1') {
  install(process.env);
}

module.exports = { install };
