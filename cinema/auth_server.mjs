import http from 'node:http';
import {createHmac, createHash, randomBytes, scrypt as scryptCallback, timingSafeEqual} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {promisify} from 'node:util';

const directory = path.dirname(fileURLToPath(import.meta.url));
const scrypt = promisify(scryptCallback);
const sessionKey = process.env.SESSION_SIGNING_KEY || '';
let publicHash = process.env.ENTRY_CREDENTIAL_HASH || '';
let adminHash = process.env.ADMIN_CREDENTIAL_HASH || '';
// Browser-enforced cookie caps prevent literally infinite persistence.
// Rolling 400-day viewer cookies mean continued use never has a fixed logout date.
// Explicit logout, password rotation, or cleared browser storage still invalidate it.
const viewerSessionDays = 400;
const viewerSessionMs = viewerSessionDays * 24 * 60 * 60 * 1000;
const adminSessionMs = 30 * 60 * 1000;
const listenPort = Number(process.env.PORT || 10000);
const maxBody = 4096;
const attempts = new Map();
const KEY_USER = '__Host-brocinema';
const KEY_ADMIN = '__Host-brocinema-admin';
const devMode = process.env.AUTH_TEST_LOCAL === '1';

if (!/^[a-f0-9]{64,}$/.test(sessionKey) ||
    !isHash(publicHash) || !isHash(adminHash)) {
  console.error('Required server-side credentials not configured; refusing to serve unprotected content.');
  process.exit(1);
}

function isHash(value) {
  return /^scrypt\$[A-Za-z0-9_-]{15,100}\$[A-Za-z0-9_-]{40,100}$/.test(value);
}
function b64(value) {
  return Buffer.from(value).toString('base64url');
}
function hashVersion(hash) {
  return createHash('sha256').update(hash).digest('hex').slice(0, 32);
}
function hmac(text) {
  return createHmac('sha256', Buffer.from(sessionKey, 'hex')).update(text).digest('base64url');
}
function constantEquals(a, b) {
  const left = Buffer.from(a || '');
  const right = Buffer.from(b || '');
  return left.length === right.length && timingSafeEqual(left, right);
}
function validCookie(req, type) {
  const name = type === 'admin' ? KEY_ADMIN : KEY_USER;
  const cookies = String(req.headers.cookie || '').split(';').map(x => x.trim());
  const found = cookies.find(x => x.startsWith(name + '='));
  if (!found) return false;
  const value = found.slice(name.length + 1);
  const [payload, signature, extra] = value.split('.');
  if (!payload || !signature || extra || !constantEquals(hmac(payload), signature)) return false;
  try {
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    const maxTtl = type === "admin" ? adminSessionMs : viewerSessionMs;
    if (data.type !== type || !Number.isFinite(data.until) || Date.now() >= data.until || data.until > Date.now() + maxTtl) return false;
    return data.version === hashVersion(type === 'admin' ? adminHash : publicHash);
  } catch {
    return false;
  }
}
function newCookie(type) {
  const name = type === 'admin' ? KEY_ADMIN : KEY_USER;
  const age = type === 'admin' ? adminSessionMs : viewerSessionMs;
  const hash = type === 'admin' ? adminHash : publicHash;
  const signed = b64(JSON.stringify({type, until: Date.now() + age, version: hashVersion(hash), nonce: b64(randomBytes(12))}));
  return name + '=' + signed + '.' + hmac(signed) + '; Path=/; Max-Age=' + Math.floor(age / 1000) +
    '; HttpOnly; SameSite=Lax' + (devMode ? '' : '; Secure');
}
function clearCookie(type) {
  return (type === 'admin' ? KEY_ADMIN : KEY_USER) + '=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax' +
    (devMode ? '' : '; Secure');
}
function headers(contentType) {
  return {
    'Content-Type': contentType,
    'Cache-Control': 'no-store, private, max-age=0',
    'Pragma': 'no-cache',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'Vary': 'Cookie'
  };
}
function json(res, status, data, moreHeaders = {}) {
  res.writeHead(status, {...headers('application/json; charset=utf-8'), ...moreHeaders});
  res.end(JSON.stringify(data));
}
function page(res, status, html, moreHeaders = {}) {
  res.writeHead(status, {
    ...headers('text/html; charset=utf-8'),
    'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
    ...moreHeaders
  });
  res.end(html);
}
function restricted(res) {
  json(res, 401, {ok: false, error: '입장 인증이 필요합니다.'});
}
function safeOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return false;
  try {
    const url = new URL(origin);
    const host = req.headers.host || '';
    return url.host === host && (url.protocol === 'https:' || (devMode && url.protocol === 'http:'));
  } catch {
    return false;
  }
}
async function readJson(req) {
  const input = [];
  let total = 0;
  for await (const chunk of req) {
    total += chunk.length;
    if (total > maxBody) throw new Error('요청 크기 제한을 초과했습니다.');
    input.push(chunk);
  }
  let value;
  try { value = JSON.parse(Buffer.concat(input).toString('utf8')); } catch { throw new Error('입력 형식 오류'); }
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('입력 형식 오류');
  return value;
}
async function verifyPassword(pass, stored) {
  if (typeof pass !== 'string' || pass.length > 256) return false;
  const [, salt, hash] = stored.split('$');
  const expected = Buffer.from(hash, 'base64url');
  const actual = await scrypt(pass, Buffer.from(salt, 'base64url'), expected.length, {N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024});
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}
async function createPasswordHash(pass) {
  const salt = randomBytes(16);
  const hash = await scrypt(pass, salt, 32, {N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024});
  return 'scrypt$' + b64(salt) + '$' + b64(hash);
}
function rateLimit(req, key, success = false) {
  // Lightweight rate limit; persistent rate-limiting requires a shared datastore.
  const ip = req.socket.remoteAddress || 'none';
  const mapKey = key + ':' + ip;
  const now = Date.now();
  const data = attempts.get(mapKey) || {count: 0, expires: now + 15 * 60 * 1000};
  if (data.expires < now) { data.count = 0; data.expires = now + 15 * 60 * 1000; }
  if (success) data.count = 0;
  else data.count++;
  attempts.set(mapKey, data);
  if (attempts.size > 5000) {
    for (const [k, v] of attempts) { if (v.expires < now) attempts.delete(k); }
  }
  return data.count > 8;
}
async function staticFile(res, rel, type, moreHeaders={}) {
  try {
    const file = await readFile(path.join(directory, rel));
    res.writeHead(200, {...headers(type), ...moreHeaders});
    res.end(file);
  } catch {
    json(res, 404, {ok:false, error:'리소스를 찾을 수 없습니다.'});
  }
}
function permittedResource(route) {
  if (route === '/' || route === '/index.html') return ['app.html', 'text/html; charset=utf-8'];
  if (route === '/catalog.json' || route === '/api/data') return ['catalog.json', 'application/json; charset=utf-8'];
  if (route === '/manifest.json') return ['manifest.json', 'application/manifest+json'];
  if (route === '/sw.js') return ['sw-secure.js', 'text/javascript; charset=utf-8'];
  if (/^\/icons\/icon-(?:192|512)\.png$/.test(route)) return [route.slice(1), 'image/png'];
  return null;
}
function remoteOperation(url, method, payload) {
  return fetch(url, {
    method,
    headers: {
      'Authorization': 'Bearer ' + process.env.RENDER_API_KEY,
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(15000)
  });
}
async function persistNewPasswordHash(type, newHash) {
  const envKey = type === 'admin' ? 'ADMIN_CREDENTIAL_HASH' : 'ENTRY_CREDENTIAL_HASH';
  const apiKey = process.env.RENDER_API_KEY;
  const serviceId = process.env.RENDER_SERVICE_ID;
  if (!apiKey || !serviceId) return {success:false, reason:'render_api_not_configured'};
  const prefix = 'https://api.render.com/v1/services/' + encodeURIComponent(serviceId);
  const updated = await remoteOperation(prefix + '/env-vars/' + envKey, 'PUT', {value:newHash});
  if (!updated.ok) throw new Error('Render credential storage rejected the change (HTTP ' + updated.status + ')');
  const deploy = await remoteOperation(prefix + '/deploys', 'POST', {deployMode:'deploy_only'});
  if (!deploy.ok) throw new Error('New credential saved; Render redeploy must be completed (HTTP ' + deploy.status + ')');
  if (type === 'admin') adminHash = newHash;
  else publicHash = newHash;
  return {success:true};
}
function redirect(res, to) {
  res.writeHead(303, {...headers('text/plain; charset=utf-8'), 'Location': to});
  res.end('Redirecting.');
}
async function handler(req, res) {
  const url = new URL(req.url, 'https://local.invalid');
  const route = url.pathname;
  const method = req.method || 'GET';
  if (route === '/healthz' && method === 'GET') {
    const sourceHost = process.env.TVWIKI_SOURCE_HOST || 'tvwiki61.net';
    json(res, 200, {ok:true,metadataSourceHost:/^tvwiki[0-9]+\.net$/.test(sourceHost)?sourceHost:'unknown'});
    return;
  }
  const authenticated = validCookie(req, 'user');
  if (method === 'GET' && route === '/login') {
    if (authenticated) { redirect(res, '/'); return; }
    await staticFile(res, 'gate.html', 'text/html; charset=utf-8'); return;
  }
  if (method === 'POST') {
    if (!safeOrigin(req)) { json(res, 403, {ok:false,error:'출처가 올바르지 않습니다.'}); return; }
    let input;
    try { input = await readJson(req); } catch (error) { json(res, 400, {ok:false,error:error.message}); return; }
    if (route === '/api/login') {
      if (rateLimit(req, 'viewer-check', true) && false) return;
      const blocked = (attempts.get('viewer:' + (req.socket.remoteAddress || 'none')) || {}).count > 8;
      if (blocked) { json(res, 429, {ok:false,error:'잠시 후 다시 시도해 주세요.'}); return; }
      const correct = await verifyPassword(input.password, publicHash);
      rateLimit(req, 'viewer', correct);
      if (!correct) { json(res, 401, {ok:false,error:'입장 비밀번호를 확인해 주세요.'}); return; }
      json(res, 200, {ok:true,sessionPolicy:"rolling",automaticRenewal:true}, {'Set-Cookie':newCookie('user')}); return;
    }
    if (route === '/api/logout') {
      json(res, 200, {ok:true}, {'Set-Cookie':[clearCookie('user'),clearCookie('admin')]}); return;
    }
    if (!authenticated) { restricted(res); return; }
    if (route === '/api/admin/login') {
      const blocked = (attempts.get('admin:' + (req.socket.remoteAddress || 'none')) || {}).count > 8;
      if (blocked) { json(res, 429, {ok:false,error:'관리자 로그인 시도 제한. 잠시 후 다시 시도해 주세요.'}); return; }
      const correct = await verifyPassword(input.password, adminHash);
      rateLimit(req, 'admin', correct);
      if (!correct) { json(res, 401, {ok:false,error:'관리자 비밀번호가 올바르지 않습니다.'}); return; }
      json(res, 200, {ok:true}, {'Set-Cookie':newCookie('admin')}); return;
    }
    if (route === '/api/admin/logout') {
      json(res, 200, {ok:true}, {'Set-Cookie':clearCookie('admin')}); return;
    }
    if (route === '/api/admin/change-password') {
      if (!validCookie(req, 'admin')) { json(res, 403, {ok:false,error:'관리자 재인증이 필요합니다.'}); return; }
      const kind = input.kind === 'admin' ? 'admin' : 'user';
      const next = input.newPassword;
      if (typeof next !== 'string' || next.length < 12 || next.length > 128) {
        json(res, 400, {ok:false,error:'새 비밀번호는 12~128자로 입력해 주세요.'}); return;
      }
      const existingHash = kind === 'admin' ? adminHash : publicHash;
      if (await verifyPassword(next, existingHash)) {
        json(res, 400, {ok:false,error:'기존과 다른 비밀번호를 사용해 주세요.'}); return;
      }
      const newHash = await createPasswordHash(next);
      try {
        const result = await persistNewPasswordHash(kind, newHash);
        if (!result.success) {
          // Do not claim the credential changed if Render API persistence is not configured.
          json(res, 409, {
            ok:false, manualAction:true,
            envKey:kind === 'admin' ? 'ADMIN_CREDENTIAL_HASH' : 'ENTRY_CREDENTIAL_HASH',
            envValue:newHash,
            error:'이 서비스에 Render API 키가 연결되지 않아 변경은 아직 적용되지 않았습니다. 관리자 권한으로 Render 환경변수 값을 변경하고 재배포해 주세요.'
          });
          return;
        }
        json(res, 200, {ok:true,message:'비밀번호를 변경하고 재배포를 요청했습니다. 기존 로그인은 만료됩니다.'},
          {'Set-Cookie':kind === 'admin' ? clearCookie('admin') : clearCookie('user')});
      } catch (error) {
        json(res, 502, {ok:false,error:'변경을 완료하지 못했습니다. Render 설정을 확인해 주세요.'});
        console.error('Credential update action failed:', error.message);
      }
      return;
    }
  }
  if (method === 'GET' && route === '/api/me') {
    json(res, 200, {authenticated,admin:authenticated && validCookie(req, 'admin')}, authenticated?{'Set-Cookie':newCookie('user')}:{ }); return;
  }
  if (method === 'GET' && route === '/api/admin/status') {
    if (!authenticated) { restricted(res); return; }
    json(res, 200, {ok:true,admin:validCookie(req,'admin'),canAutoRotate:Boolean(process.env.RENDER_API_KEY && process.env.RENDER_SERVICE_ID)}, {'Set-Cookie':newCookie('user')}); return;
  }
  if (method === 'GET' && route === '/admin') {
    if (!authenticated) { redirect(res, '/login'); return; }
    await staticFile(res, 'admin.html', 'text/html; charset=utf-8', {'Set-Cookie':newCookie('user')}); return;
  }
  if (method === 'GET' && !authenticated && (route === '/' || route === '/index.html')) {
    await staticFile(res, 'gate.html', 'text/html; charset=utf-8'); return;
  }
  // The PWA manifest and its icons are deliberately public: they contain
  // only app metadata and artwork. Movie content remains session-protected.
  // This lets visitors install the independent app directly from the gate.
  if (method === 'GET' && route === '/sw.js') {
    await staticFile(res, 'sw-secure.js', 'text/javascript; charset=utf-8'); return;
  }
  if (method === 'GET' && route === '/manifest.json') {
    await staticFile(res, 'manifest.json', 'application/manifest+json'); return;
  }
  if (method === 'GET' && /^\/icons\/icon-(?:192|512)\.png$/.test(route)) {
    await staticFile(res, route.slice(1), 'image/png'); return;
  }
  if (method === 'GET') {
    const allow = permittedResource(route);
    if (allow) {
      if (!authenticated) { restricted(res); return; }
      await staticFile(res, ...allow, {'Set-Cookie':newCookie('user')}); return;
    }
  }
  json(res, 404, {ok:false,error:'페이지를 찾을 수 없습니다.'});
}
const server = http.createServer((req,res) => {
  handler(req,res).catch(error => {
    console.error('Unhandled request:', error?.message || String(error));
    if (!res.headersSent) json(res, 500, {ok:false,error:'서버 오류입니다.'});
    else res.destroy();
  });
});
server.listen(listenPort, '0.0.0.0', () => console.log('BRO CINEMA secure access server listening'));
