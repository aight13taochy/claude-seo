// Pins one hostname to a pre-validated IP inside a Node.js process.
//
// Loaded by scripts/unlighthouse_run.py through NODE_OPTIONS=--require, so it
// runs in every Node process the unlighthouse-ci run starts (npx, the
// unlighthouse CLI, its Lighthouse workers). Unlighthouse fetches the audited
// site from Node with axios before Chromium ever sees it; without this pin
// Node's own lookup would resolve the host a second time, after
// url_safety.validate_url_strict() checked it, and a DNS-rebinding answer
// could point that request at an internal address.
//
// Only the pinned host is rewritten. Every other lookup (the npm registry,
// localhost for the Lighthouse <-> Chromium connection) goes to the original
// resolver unchanged.
//
// Environment:
//   CLAUDE_SEO_PIN_HOST  hostname to pin (lowercase, punycode, no trailing dot)
//   CLAUDE_SEO_PIN_IP    IPv4 or IPv6 literal it must connect to
"use strict";

const dns = require("node:dns");
const net = require("node:net");
const util = require("node:util");

const pinHost = (process.env.CLAUDE_SEO_PIN_HOST || "").toLowerCase();
const pinIp = process.env.CLAUDE_SEO_PIN_IP || "";
const pinFamily = net.isIP(pinIp);

function isPinned(hostname) {
  return typeof hostname === "string"
    && hostname.toLowerCase().replace(/\.$/, "") === pinHost;
}

if (pinHost && pinFamily) {
  const originalLookup = dns.lookup;
  dns.lookup = function lookup(hostname, options, callback) {
    if (!isPinned(hostname)) {
      return originalLookup.apply(this, arguments);
    }
    if (typeof options === "function") {
      callback = options;
      options = {};
    }
    if (typeof options === "number") {
      options = { family: options };
    }
    const opts = options || {};
    const family = opts.family === "IPv4" ? 4 : opts.family === "IPv6" ? 6 : opts.family;
    process.nextTick(() => {
      if (family && family !== pinFamily) {
        const err = new Error(`getaddrinfo ENOTFOUND ${hostname}`);
        err.code = "ENOTFOUND";
        err.hostname = hostname;
        callback(err);
      } else if (opts.all) {
        callback(null, [{ address: pinIp, family: pinFamily }]);
      } else {
        callback(null, pinIp, pinFamily);
      }
    });
    return {};
  };

  const originalPromiseLookup = dns.promises.lookup;
  dns.promises.lookup = function lookup(hostname, options) {
    if (!isPinned(hostname)) {
      return originalPromiseLookup.apply(this, arguments);
    }
    return new Promise((resolve, reject) => {
      dns.lookup(hostname, options, (err, address, family) => {
        if (err) reject(err);
        else resolve(Array.isArray(address) ? address : { address, family });
      });
    });
  };
  // util.promisify(dns.lookup) must keep resolving to { address, family }.
  dns.lookup[util.promisify.custom] = (hostname, options) => dns.promises.lookup(hostname, options);
}
