import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('./security-ui.js',import.meta.url),'utf8');
function fixture(admin='synthetic-admin'){
  const calls=[];
  const window={location:new URL('http://127.0.0.1:31999/'),mcJetonAdmin:admin,fetch:(resource,options)=>{calls.push({resource,options});return Promise.resolve('captured')}};
  vm.runInNewContext(source,{window,URL,Request,Headers});
  return {fetch:window.fetch,calls};
}
function headers(call){return new Headers(call.options?.headers||(call.resource instanceof Request?call.resource.headers:undefined))}

test('same-origin connector mutation receives existing admin session',async()=>{
 const f=fixture();await f.fetch('/api/mc/connectors/save',{method:'POST',body:'{}'});
 assert.equal(headers(f.calls[0]).get('X-MC-Admin'),'synthetic-admin');assert.equal(f.calls[0].options.body,'{}');
});
test('external origins never receive injected admin credentials',async()=>{
 for(const url of ['https://example.invalid/api/mc/connectors/save','http://localhost:31999/api/mc/connectors/save','http://127.0.0.1:32000/api/mc/connectors/save','//example.invalid/api/mc/connectors/save']){
  const f=fixture();await f.fetch(url,{method:'POST'});assert.equal(headers(f.calls[0]).has('X-MC-Admin'),false,url);
 }
});
test('read requests and unrelated routes do not receive injected admin credentials',async()=>{
 for(const [url,method] of [['/api/mc/connectors/list','POST'],['/api/mc/connectors/save','GET'],['/api/mc/job','POST']]){
  const f=fixture();await f.fetch(url,{method});assert.equal(headers(f.calls[0]).has('X-MC-Admin'),false);
 }
});
test('agent credentials cannot be implicitly elevated',async()=>{
 const f=fixture();await f.fetch('/api/mc/connectors/save',{method:'POST',headers:{'x-mc-agent-token':'synthetic-agent'}});
 assert.equal(headers(f.calls[0]).has('X-MC-Admin'),false);assert.equal(headers(f.calls[0]).get('X-MC-Agent-Token'),'synthetic-agent');
});
test('an explicitly supplied admin credential is preserved',async()=>{
 const f=fixture();await f.fetch('/api/mc/connectors/save',{method:'POST',headers:{'X-MC-Admin':'explicit-admin'}});
 assert.equal(headers(f.calls[0]).get('X-MC-Admin'),'explicit-admin');
});
test('Request objects retain headers and agent identity',async()=>{
 const f=fixture();const request=new Request('http://127.0.0.1:31999/api/mc/connectors/save',{method:'POST',headers:{'X-MC-Agent-Token':'synthetic-agent'}});
 await f.fetch(request);assert.equal(f.calls[0].resource,request);assert.equal(headers(f.calls[0]).has('X-MC-Admin'),false);
 const human=new Request(request.url,{method:'POST',headers:{'X-MC-Token':'synthetic-session'}});await f.fetch(human);
 assert.equal(headers(f.calls[1]).get('X-MC-Token'),'synthetic-session');assert.equal(headers(f.calls[1]).get('X-MC-Admin'),'synthetic-admin');
});
test('empty admin session does not invent credentials',async()=>{
 const f=fixture('');await f.fetch('/api/mc/connectors/save',{method:'POST'});assert.equal(headers(f.calls[0]).has('X-MC-Admin'),false);
});
