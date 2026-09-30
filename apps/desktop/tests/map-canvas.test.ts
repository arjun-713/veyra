// Real Svelte effects, OrbitControls and WebGL buffers in headless Chrome.
// Set CHROME_BIN to run on another host; no browser package is required.
import assert from 'node:assert/strict';
import {spawn,type ChildProcess} from 'node:child_process';
import {existsSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {after,before,test} from 'node:test';
import {createServer,type ViteDevServer} from 'vite';

const chrome=process.env.CHROME_BIN??['/usr/bin/google-chrome','/usr/bin/chromium','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(existsSync);
const root=new URL('..',import.meta.url).pathname;
let server:ViteDevServer,browser:ChildProcess,socket:WebSocket,profile:string;
let nextId=0;
const pending=new Map<number,{resolve:(value:any)=>void;reject:(error:Error)=>void}>();
const errors:string[]=[];
async function command(method:string,params:Record<string,unknown>={}){
 const id=++nextId;
 const result=new Promise<any>((resolve,reject)=>pending.set(id,{resolve,reject}));
 socket.send(JSON.stringify({id,method,params}));return result;
}
async function evaluate(expression:string){
 const result=await command('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
 assert.equal(result.exceptionDetails,undefined,JSON.stringify(result.exceptionDetails));
 return result.result.value;
}
before(async()=>{
 if(!chrome)return;
 server=await createServer({root,configFile:join(root,'vite.renderer.config.ts'),logLevel:'error',server:{port:0,strictPort:false,hmr:false}});
 await server.listen();
 profile=mkdtempSync(join(tmpdir(),'veyra-canvas-test-'));
 browser=spawn(chrome,['--headless','--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader',
  '--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
 const endpoint=await new Promise<string>((resolve,reject)=>{
  let stderr='';const timeout=setTimeout(()=>reject(new Error('Chrome did not start')),15000);
  browser.on('error',reject);
  browser.stderr!.on('data',chunk=>{stderr+=chunk;const match=stderr.match(/DevTools listening on (ws:\/\/\S+)/);if(match){clearTimeout(timeout);resolve(match[1]);}});
 });
 const targets=await fetch(`http://${new URL(endpoint).host}/json/list`).then(r=>r.json()) as any[];
 socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
 await new Promise<void>((resolve,reject)=>{socket.onopen=()=>resolve();socket.onerror=()=>reject(new Error('CDP connection failed'));});
 socket.onmessage=event=>{
  const message=JSON.parse(String(event.data));
  if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description??message.params.exceptionDetails.text);
  if(message.method==='Runtime.consoleAPICalled'&&message.params.type==='error')errors.push(message.params.args.map((arg:any)=>arg.value??arg.description).join(' '));
  if(message.method==='Network.loadingFailed')errors.push(message.params.errorText);
  const request=pending.get(message.id);if(!request)return;pending.delete(message.id);
  if(message.error)request.reject(new Error(message.error.message));else request.resolve(message.result);
 };
 await command('Runtime.enable');
 await command('Network.enable');
 const navigation=await command('Page.navigate',{url:`${server.resolvedUrls!.local[0]}tests/fixtures/map-canvas.html`});
 assert.equal(navigation.errorText,undefined);
 const deadline=Date.now()+15000;
 while(Date.now()<deadline){
  if(await evaluate('!!window.canvasProbe?.snapshot'))return;
  await new Promise(resolve=>setTimeout(resolve,25));
 }
 assert.fail(`Canvas did not mount: ${errors.join('\n')} ${await evaluate('location.href+document.body.innerHTML')}`);
}, {timeout:30000});
after(async()=>{
 socket?.close();
 if(browser&&!browser.killed){const exited=new Promise(resolve=>browser.once('exit',resolve));browser.kill();await exited;}
 await server?.close();
 if(profile)rmSync(profile,{recursive:true,force:true});
});

test('stats feedback settles and replay keeps GPU buffers and camera across frames',{skip:!chrome,timeout:15000},async()=>{
 const first=await evaluate('canvasProbe.present(0)');
 await evaluate('canvasProbe.settle()');
 assert.equal(await evaluate('canvasProbe.frameStatsCalls'),first.frameStatsCalls,'stats must not invalidate frame effects');
 assert.equal(await evaluate('canvasProbe.snapshot.cellVersion'),first.cellVersion);
 const next=await evaluate('canvasProbe.present(1)');
 assert.equal(next.points,2);assert.equal(next.cells,1);
 assert.equal(typeof first.pointBuffer,'number');
 assert.equal(next.pointBuffer,first.pointBuffer);assert.equal(next.creates,first.creates);
 assert.deepEqual(next.camera,first.camera,'new frames must not reset the orbit camera');
 assert.equal(await evaluate('canvasProbe.deletes'),0,'replay must not dispose GPU buffers');
 assert.deepEqual(errors,[]);
});

test('empty scan uploads no point buffer tail',{skip:!chrome,timeout:15000},async()=>{
 await evaluate('canvasProbe.clear()');
 await evaluate('canvasProbe.present(0)');
 await evaluate('canvasProbe.uploads=[]');
 const empty=await evaluate('canvasProbe.present(1,0)');
 assert.equal(empty.points,0);
 const uploads=await evaluate('canvasProbe.uploads') as number[];
 assert.ok(uploads.every(bytes=>bytes<=64),`empty scan uploaded unused capacity: ${uploads}`);
 await evaluate('canvasProbe.uploads=[]');
 assert.equal((await evaluate('canvasProbe.present(2)')).points,2);
 assert.ok((await evaluate('canvasProbe.uploads') as number[]).includes(24),'the next nonempty scan still uploads its points');
});

test('empty map uploads no instance buffer tail',{skip:!chrome,timeout:15000},async()=>{
 await evaluate('canvasProbe.clear()');
 await evaluate('canvasProbe.present(0)');
 await evaluate('canvasProbe.uploads=[]');
 const empty=await evaluate('canvasProbe.present(1,2,{cells:{offset:136,count:0,stride:68}})');
 assert.equal(empty.cells,0);
 const uploads=await evaluate('canvasProbe.uploads') as number[];
 assert.ok(uploads.every(bytes=>bytes<=24),`empty map uploaded unused capacity: ${uploads}`);
 await evaluate('canvasProbe.uploads=[]');
 assert.equal((await evaluate('canvasProbe.present(2)')).cells,1);
 assert.ok((await evaluate('canvasProbe.uploads') as number[]).includes(64),'the next nonempty map still uploads its instances');
});

test('follow translates the camera without resetting its offset',{skip:!chrome,timeout:15000},async()=>{
 await evaluate('canvasProbe.clear()');
 await evaluate('canvasProbe.settings({follow:true,view:"driver"})');
 const first=await evaluate('canvasProbe.present(0)');
 const next=await evaluate('canvasProbe.present(1)');
 assert.ok(Math.abs(next.camera[0]-first.camera[0]-1)<1e-6);
 assert.ok(Math.abs(next.camera[1]-first.camera[1])<1e-6);
 assert.ok(Math.abs(next.camera[2]-first.camera[2])<1e-6);
 assert.deepEqual(errors,[]);
});
