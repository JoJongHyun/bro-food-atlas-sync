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
test('BRO CINEMA rolling session, protected app, admin separation and safe credential rotation', {timeout:25000},async()=>{
  const child=spawn(process.execPath,['cinema/auth_server.mjs'],{
    env:{...process.env,PORT:String(port),AUTH_TEST_LOCAL:'1',ENTRY_CREDENTIAL_HASH:hash(viewer),ADMIN_CREDENTIAL_HASH:hash(admin),SESSION_SIGNING_KEY:'b'.repeat(96),RENDER_API_KEY:''},
    stdio:'ignore'
  });
  try {
    await waitUntilReady();
    const home=await fetch(base+'/');
    assert.equal(home.status,200);
    const gateHtml=await home.text();
    assert.match(gateHtml,/입장 비밀번호/);
    assert.match(gateHtml,/rel="manifest"/);
    assert.match(gateHtml,/상단 X 없는 앱으로 설치하기/);
    // Public PWA install assets are metadata only, even for logged-out users.
    const manifest=await fetch(base+'/manifest.json');
    assert.equal(manifest.status,200);
    assert.match(manifest.headers.get('content-type'),/application\/manifest\+json/);
    const appManifest=await manifest.json();
    assert.equal(appManifest.display,'standalone');
    assert.equal(appManifest.start_url,'/');
    assert.equal(appManifest.scope,'/');
    for(const size of [192,512]){
      const icon=await fetch(base+'/icons/icon-'+size+'.png');
      assert.equal(icon.status,200);
      assert.match(icon.headers.get('content-type'),/image\/png/);
      assert.ok((await icon.arrayBuffer()).byteLength>400);
    }
    assert.equal((await fetch(base+'/sw.js')).status,200);
    for(const route of ['/catalog.json','/api/data','/index.html']){
      const restricted=await fetch(base+route);
      assert.equal(restricted.status,route==='/index.html'?200:401);
    }
    assert.equal((await post('/api/login',{password:'wrong'})).status,401);
    const ok=await post('/api/login',{password:viewer});
    assert.equal(ok.status,200);
    assert.match(ok.headers.get('set-cookie'),/Max-Age=34560000/);  // 400 days, renewed on use
    const loginData=await ok.json();
    assert.equal(loginData.sessionPolicy,'rolling');
    assert.equal(loginData.automaticRenewal,true);
    assert.match(ok.headers.get('set-cookie'),/HttpOnly/);
    assert.match(ok.headers.get('set-cookie'),/SameSite=Lax/);
    const session=cookie(ok);
    const catalog=await fetch(base+'/catalog.json',{headers:{Cookie:session}});
    assert.equal(catalog.status,200);
    assert.match(catalog.headers.get('set-cookie'),/Max-Age=34560000/); // renewed on each request
    assert.notEqual(cookie(catalog),session); // token is rotated; not tied to an absolute login date
    const userHome=await fetch(base+'/',{headers:{Cookie:session}});
    assert.equal(userHome.status,200);
    assert.match(await userHome.text(),/BRO CINEMA/);
    assert.match(userHome.headers.get('set-cookie'),/Max-Age=34560000/);
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
