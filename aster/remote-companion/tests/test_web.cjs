// Deterministic DOM harness, not a real-browser/PWA installation test.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(__dirname + '/../web/app.js', 'utf8');
function app(fetcher = async () => ({ok: true, json: async () => ({messages: []})}), stored = '[]') {
  const nodes = new Map();
  const make = id => ({id, value: '', textContent: '', children: [], handlers: {}, addEventListener(e, f) {this.handlers[e] = f;}, prepend(x) {this.children.unshift(x);nodes.set(x.id,x);x.remove = () => this.children.splice(this.children.indexOf(x),1);}, replaceChildren(){this.children=[];}, get lastChild(){return this.children.at(-1);}});
  const document = {getElementById(id) {if(id.startsWith('receipt-')) return nodes.get(id);if(!nodes.has(id))nodes.set(id,make(id));return nodes.get(id);},createElement(){return make('');}};
  const data = new Map([['aster.remote.outbox.v1', stored]]);
  const timers = new Map(); let next = 0;
  const context = vm.createContext({document, localStorage:{getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)},crypto:webcrypto,TextEncoder,AbortController,fetch:fetcher,window:{isSecureContext:true},navigator:{},setInterval:f=>{timers.set(++next,f);return next;},clearInterval:id=>timers.delete(id),setTimeout,clearTimeout});
  vm.runInContext(source,context);
  return {context,nodes,data,timers, get:id=>document.getElementById(id), run:s=>vm.runInContext(s,context), event(id,e='click'){document.getElementById(id).handlers[e]({preventDefault(){}});}};
}
const tick = () => new Promise(r=>setImmediate(r));
test('offline queue survives reload, expires and stays bounded',()=>{
  const a=app();a.get('prompt').value='Hello';a.event('compose','submit');
  assert.equal(JSON.parse(a.data.get('aster.remote.outbox.v1')).length,1);
  const b=app(undefined,a.data.get('aster.remote.outbox.v1'));
  assert.match(b.get('queue').textContent,/1 message/);
  for(let i=0;i<55;i++){b.get('prompt').value='text';b.event('compose','submit');}
  assert.equal(JSON.parse(b.data.get('aster.remote.outbox.v1')).length,50);
  b.event('clear');assert.equal(b.data.get('aster.remote.outbox.v1'),'[]');
  const c=app(undefined,JSON.stringify([{id:'a'.repeat(32),body:'expired',expires:1}]));
  assert.equal(c.data.get('aster.remote.outbox.v1'),'[]');
});
test('receipt HTML is text and repeated inbox results do not duplicate it',async()=>{
  const calls=[];
  const a=app(async(path,opts)=>{calls.push([path,opts]);return {ok:true,json:async()=>({messages:[{id:'a'.repeat(32),body:'<img onerror=evil()>',expires:Date.now()/1000+60}]})};});
  a.get('key').value='fixture-only-'.padEnd(40,'x');a.event('connect');await tick();
  await a.run('sync()');
  assert.equal(a.get('receipts').children.length,1);
  assert.equal(a.get('receipts').children[0].textContent,'<img onerror=evil()>');
  assert.equal(a.get('key').value,'');assert.equal(a.timers.size,1);
  assert.ok(calls.some(c=>c[0]==='/v1/ack'));
  a.event('stop');assert.equal(a.timers.size,0);
});
test('disconnect aborts a request and stale success cannot reconnect',async()=>{
  let resolve;
  const a=app(()=>new Promise(r=>resolve=r));
  a.get('key').value='fixture-only-'.padEnd(40,'x');a.event('connect');a.event('stop');
  resolve({ok:true,json:async()=>({messages:[]})});await tick();
  assert.match(a.get('status').textContent,/Disconnected/);
  assert.equal(a.run('token'),'');assert.equal(a.timers.size,0);
});
test('auth expiry stops retries, reconnect and failed delivery retain exact message ID',async()=>{
  const a=app(async()=>({ok:false,status:401}));
  a.get('prompt').value='pending';a.event('compose','submit');
  const before=a.data.get('aster.remote.outbox.v1');
  a.get('key').value='fixture-only-'.padEnd(40,'x');a.event('connect');await tick();
  assert.match(a.get('status').textContent,/expired/);assert.equal(a.timers.size,0);
  assert.equal(a.data.get('aster.remote.outbox.v1'),before);
  a.get('key').value='fixture-only-'.padEnd(40,'x');a.event('connect');await tick();
  assert.equal(a.data.get('aster.remote.outbox.v1'),before);
});

test('clear aborts an in-flight snapshot before later queued messages are sent',async()=>{
  let resolve; const sent=[];
  const a=app((path,options)=>{sent.push([path,options.body]);return new Promise(r=>resolve=r);});
  for (const text of ['first','second']) {a.get('prompt').value=text;a.event('compose','submit');}
  a.get('key').value='fixture-only-'.padEnd(40,'x');a.event('connect');
  a.event('clear');
  resolve({ok:true,json:async()=>({status:'queued_for_workstation'})});await tick();
  assert.equal(sent.length,1);
  assert.equal(a.data.get('aster.remote.outbox.v1'),'[]');
  assert.equal(a.timers.size,0);
  assert.match(a.get('status').textContent,/cannot be recalled/);
});
