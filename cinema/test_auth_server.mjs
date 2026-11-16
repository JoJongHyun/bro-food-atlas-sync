import test from 'node:test';
import assert from 'node:assert/strict';
import {scryptSync} from 'node:crypto';
import {spawn} from 'node:child_process';

const port = 19763;
const base = 'http://127.0.0.1:' + port;
const viewer = 'LocalOnlyViewer-Strong-Password-2026';
const admin = 'LocalOnlyAdmin-Strong-Password-2026';
function hash(password) {
  const salt = Buffer.from('test-salt-not-secret');
  const digest = scryptSync(password, salt, 32, {N:16384,r:8,p:1,maxmem:64*1024*1024});
  return 'scrypt$' + salt.toString('base64url') + '$' + digest.toString('base64url');
}
async function waitUntilReady() {
  for (let n=0;n<80;n++){
    try { const r=await fetch(base+'/healthz');if(r.status===200)return; }catch{}
    await new Promise(r=>setTimeout(r,100));
  }
  throw new Error('Auth server never became ready');
}
function cookie(resp) {
  return String(resp.headers.get('set-cookie')||'').split(';')[0];
}
async function post(route,data,cookies='') {
  return fetch(base+route, {
    method:'POST',
    headers:{'Origin':base,'Content-Type':'application/json',...(cookies?{'Cookie':cookies}:{})},
    body:JSON.stringify(data),
    redirect:'manual'
  });
}
test('BRO CINEMA auth, 30-day session, admin separation and no-API persistence response', {timeout:25000},async()=>{
  const child=spawn(process.execPath,['cinema/auth_server.mjs'],{
    env:{...process.env,PORT:String(port),AUTH_TEST_LOCAL:'1',ENTRY_CREDENTIAL_HASH:hash(viewer),ADMIN_CREDENTIAL_HASH:hash(admin),SESSION_SIGNING_KEY:'b'.repeat(96),RENDER_API_KEY:''},
    stdio:'ignore'
  });
  try {
    await waitUntilReady();
    const home=await fetch(base+'/');
    assert.equal(home.status,200);
    assert.match(await home.text(),/입장 비밀번호/);
    for(const route of ['/catalog.json','/api/data','/index.html']){
      const restricted=await fetch(base+route);
      assert.equal(restricted.status,route==='/index.html'?200:401);
    }
    assert.equal((await post('/api/login',{password:'wrong'})).status,401);
    const ok=await post('/api/login',{password:viewer});
    assert.equal(ok.status,200);
    assert.match(ok.headers.get('set-cookie'),/Max-Age=2592000/);
    assert.match(ok.headers.get('set-cookie'),/HttpOnly/);
    assert.match(ok.headers.get('set-cookie'),/SameSite=Lax/);
    const session=cookie(ok);
    const catalog=await fetch(base+'/catalog.json',{headers:{Cookie:session}});
    assert.equal(catalog.status,200);
    const data=await catalog.json();
    assert.ok(Array.isArray(data.items));
    const adminUnauth=await fetch(base+'/api/admin/status',{headers:{Cookie:session}});
    assert.equal((await adminUnauth.json()).admin,false);
    const wrongAdmin=await post('/api/admin/login',{password:'not-the-admin-code'},session);
    assert.equal(wrongAdmin.status,401);
    const elevated=await post('/api/admin/login',{password:admin},session);
    assert.equal(elevated.status,200);
    const adminCookie=cookie(elevated),both=session+'; '+adminCookie;
    const activeAdmin=await fetch(base+'/api/admin/status',{headers:{Cookie:both}});
    assert.equal((await activeAdmin.json()).admin,true);
    const rejected=await post('/api/admin/change-password',{kind:'user',newPassword:'AnotherStrongCode12345'},session);
    assert.equal(rejected.status,403);
    const preview=await post('/api/admin/change-password',{kind:'user',newPassword:'AnotherStrongCode12345'},both);
    assert.equal(preview.status,409);
    const previewData=await preview.json();
    assert.equal(previewData.manualAction,true);
    assert.equal(previewData.envKey,'ENTRY_CREDENTIAL_HASH');
    assert.match(previewData.envValue,/^scrypt\$/);
    const logout=await post('/api/logout',{},session);
    assert.equal(logout.status,200);
    assert.match(logout.headers.get('set-cookie'),/Max-Age=0/);
    const another=await fetch(base+'/api/me');
    assert.equal((await another.json()).authenticated,false);
  }finally {
    child.kill('SIGTERM');
  }
});
