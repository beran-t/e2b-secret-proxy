'use strict';

const http = require('http');
const https = require('https');
const net = require('net');
const fs = require('fs');
const { URL } = require('url');

const PORT = parseInt(process.env.PROXY_PORT || '3128', 10);
const CONFIG_FILE = '/etc/proxy/config.json';
const CONFIG_POLL_MS = 2000; // Check for config file changes every 2s

// --- Glob matching ---

function globToRegex(pattern) {
  let regex = '';
  let i = 0;
  while (i < pattern.length) {
    const ch = pattern[i];
    if (ch === '*') {
      if (pattern[i + 1] === '*') {
        regex += '.*';
        i += 2;
        if (pattern[i] === '.') { i++; regex += '\\.'; } // skip dot after **
        continue;
      }
      regex += '[^.]*';
      i++;
    } else if (ch === '?') {
      regex += '[^.]';
      i++;
    } else if ('.+^${}()|[]\\'.includes(ch)) {
      regex += '\\' + ch;
      i++;
    } else {
      regex += ch;
      i++;
    }
  }
  return new RegExp('^' + regex + '$', 'i');
}

// --- Self-test mode ---

if (process.argv.includes('--test')) {
  const assert = (cond, msg) => {
    if (!cond) { console.error('FAIL:', msg); process.exit(1); }
    console.log('  PASS:', msg);
  };

  console.log('Running glob matching tests...\n');

  // Exact match
  assert(globToRegex('api.openai.com').test('api.openai.com'), 'exact match');
  assert(!globToRegex('api.openai.com').test('other.openai.com'), 'exact no match');

  // Single wildcard
  assert(globToRegex('*.openai.com').test('api.openai.com'), '*.openai.com matches api.openai.com');
  assert(!globToRegex('*.openai.com').test('api.v2.openai.com'), '*.openai.com does not match api.v2.openai.com');
  assert(globToRegex('*.openai.com').test('chat.openai.com'), '*.openai.com matches chat.openai.com');

  // Double wildcard
  assert(globToRegex('**.openai.com').test('api.openai.com'), '**.openai.com matches api.openai.com');
  assert(globToRegex('**.openai.com').test('api.v2.openai.com'), '**.openai.com matches api.v2.openai.com');

  // Case insensitivity
  assert(globToRegex('API.OpenAI.com').test('api.openai.com'), 'case insensitive');
  assert(globToRegex('api.openai.com').test('API.OPENAI.COM'), 'case insensitive reverse');

  // Question mark
  assert(globToRegex('api?.openai.com').test('api1.openai.com'), '? matches single char');
  assert(!globToRegex('api?.openai.com').test('api12.openai.com'), '? does not match two chars');

  // Full wildcard
  assert(globToRegex('*.amazonaws.com').test('s3.amazonaws.com'), '*.amazonaws.com matches s3');
  assert(globToRegex('*.amazonaws.com').test('dynamodb.amazonaws.com'), '*.amazonaws.com matches dynamodb');

  console.log('\nAll tests passed.');
  process.exit(0);
}

// --- Config loading ---

// Mutable rules array — reloaded on SIGHUP or config file changes
let compiledRules = [];
let lastConfigHash = '';

function loadConfig() {
  // Try config file first (written post-sandbox-creation)
  if (fs.existsSync(CONFIG_FILE)) {
    try {
      return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
    } catch (e) {
      console.error('[secret-proxy] Invalid JSON in', CONFIG_FILE + ':', e.message);
      return null;
    }
  }

  // Try env var
  const envConfig = process.env.PROXY_CONFIG;
  if (envConfig) {
    try {
      return JSON.parse(envConfig);
    } catch (e) {
      console.error('[secret-proxy] Invalid JSON in PROXY_CONFIG:', e.message);
      return null;
    }
  }

  return null;
}

function compileRules(config) {
  if (!config || !Array.isArray(config.rules)) return [];
  return config.rules.map((rule) => {
    if (!rule.match || typeof rule.match !== 'string') return null;
    if (!rule.headers || typeof rule.headers !== 'object') return null;
    return {
      pattern: rule.match,
      regex: globToRegex(rule.match),
      headers: rule.headers,
      headerCount: Object.keys(rule.headers).length,
    };
  }).filter(Boolean);
}

function reloadConfig(source) {
  const config = loadConfig();
  const newRules = compileRules(config);
  compiledRules = newRules;
  console.log(`[secret-proxy] ${source}: Loaded ${compiledRules.length} rule(s):`);
  for (const rule of compiledRules) {
    console.log(`[secret-proxy]   - ${rule.pattern} (injecting ${rule.headerCount} header(s))`);
  }
  if (compiledRules.length === 0) {
    console.log('[secret-proxy]   No rules configured, all requests pass through unchanged');
  }
}

// Initial load
reloadConfig('Startup');

// Reload on SIGHUP
process.on('SIGHUP', () => reloadConfig('SIGHUP'));

// Poll for config file changes (handles E2B snapshot-restore where
// the config file is written after the proxy is already running)
let configPollTimer = setInterval(() => {
  try {
    if (!fs.existsSync(CONFIG_FILE)) return;
    const content = fs.readFileSync(CONFIG_FILE, 'utf8');
    if (content === lastConfigHash) return;
    lastConfigHash = content;
    reloadConfig('File change detected');
  } catch {
    // Ignore read errors
  }
}, CONFIG_POLL_MS);
configPollTimer.unref(); // Don't prevent process exit

// --- Header injection ---

function findMatchingHeaders(hostname) {
  const merged = {};
  let injected = false;
  for (const rule of compiledRules) {
    if (rule.regex.test(hostname)) {
      Object.assign(merged, rule.headers);
      injected = true;
    }
  }
  return { headers: merged, injected };
}

// --- Logging ---

function log(method, host, path, injected) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${method} ${host}${path} -> injected=${injected}`);
}

function logConnect(host, port) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] CONNECT ${host}:${port} -> tunnel (no injection)`);
}

function logError(host, err) {
  const ts = new Date().toISOString();
  console.error(`[${ts}] ERROR ${host}: ${err.message}`);
}

// --- HTTP forward proxy ---

const server = http.createServer((clientReq, clientRes) => {
  let targetUrl;
  try {
    targetUrl = new URL(clientReq.url);
  } catch {
    // Not an absolute URL — could be a relative request to the proxy itself
    clientRes.writeHead(400);
    clientRes.end('Bad Request: proxy expects absolute URLs');
    return;
  }

  const hostname = targetUrl.hostname;
  const port = targetUrl.port || (targetUrl.protocol === 'https:' ? 443 : 80);
  const isHttps = targetUrl.protocol === 'https:';
  const path = targetUrl.pathname + targetUrl.search;

  // Find matching rules and get headers to inject
  const { headers: injectHeaders, injected } = findMatchingHeaders(hostname);

  // Build outgoing headers
  const outHeaders = { ...clientReq.headers };
  delete outHeaders['proxy-connection'];
  delete outHeaders['proxy-authorization'];
  outHeaders.host = targetUrl.host;
  Object.assign(outHeaders, injectHeaders);

  log(clientReq.method, hostname, path, injected);

  const transport = isHttps ? https : http;
  const proxyReq = transport.request(
    {
      hostname,
      port,
      path,
      method: clientReq.method,
      headers: outHeaders,
    },
    (proxyRes) => {
      clientRes.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(clientRes, { end: true });
    }
  );

  proxyReq.on('error', (err) => {
    logError(hostname, err);
    if (!clientRes.headersSent) {
      clientRes.writeHead(502);
      clientRes.end('Bad Gateway');
    }
  });

  clientReq.pipe(proxyReq, { end: true });
});

// --- CONNECT tunneling (HTTPS passthrough, no injection) ---

server.on('connect', (clientReq, clientSocket, head) => {
  const [hostname, portStr] = clientReq.url.split(':');
  const port = parseInt(portStr, 10) || 443;

  logConnect(hostname, port);

  const targetSocket = net.connect(port, hostname, () => {
    clientSocket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
    if (head.length > 0) targetSocket.write(head);
    targetSocket.pipe(clientSocket);
    clientSocket.pipe(targetSocket);
  });

  targetSocket.on('error', (err) => {
    logError(hostname + ':' + port, err);
    clientSocket.end();
  });

  clientSocket.on('error', () => targetSocket.destroy());
});

// --- Graceful shutdown ---

function shutdown() {
  console.log('[secret-proxy] Shutting down...');
  clearInterval(configPollTimer);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 3000);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// --- Start ---

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[secret-proxy] Listening on 127.0.0.1:${PORT}`);
  console.log('[secret-proxy] Ready (watching for config file changes)');
});
