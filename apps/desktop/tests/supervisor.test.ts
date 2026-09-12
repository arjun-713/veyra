import {test} from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {RuntimeSupervisor,terminationTarget} from '../src/supervisor.ts';

function within<T>(promise:Promise<T>,milliseconds=500):Promise<T>{
 return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('operation timed out')),milliseconds);
  promise.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});
 });
}

test('forced shutdown addresses the whole Unix runtime process group',()=>{
 assert.equal(terminationTarget(42,'linux'),-42);
 assert.equal(terminationTarget(42,'darwin'),-42);
 assert.equal(terminationTarget(42,'win32'),42);
});

test('supervisor rejects pending commands when backend dies and reports process identity',async t=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setTimeout(()=>process.exit(7),100)'],cwd:process.cwd()});
 t.after(()=>runtime.stop());
 const events:any[]=[],fatals:any[]=[];runtime.on('event',e=>events.push(e));runtime.on('fatal',e=>fatals.push(e));runtime.start();
 await assert.rejects(runtime.request('status',{}),/exited/);
 assert.equal(events.at(-1).error.process,'runtime');
 assert.equal(events.at(-1).state,'error');
 assert.equal(fatals.length,1);
});

test('backend status errors remain ordinary events and do not signal a process fatal',async t=>{
 const script=`const m=Buffer.from(JSON.stringify({type:'status',state:'error',error:{process:'perception',message:'model missing'}}));const h=Buffer.alloc(16);h.write('VYRA');h.writeUInt16LE(1,4);h.writeUInt16LE(1,6);h.writeUInt32LE(m.length,8);process.stdout.write(Buffer.concat([h,m]));setInterval(()=>{},1000)`;
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e',script],cwd:process.cwd()});
 t.after(()=>runtime.stop());
 const fatals:any[]=[];runtime.on('fatal',e=>fatals.push(e));
 const event=once(runtime,'event');runtime.start();
 const [status]=await within(event);
 assert.equal(status.error.process,'perception');
 assert.equal(fatals.length,0);
 await runtime.stop();
});

test('supervisor bounds pending requests and terminates a silent child',async t=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setInterval(()=>{},1000)'],cwd:process.cwd(),requestTimeoutMs:80});
 t.after(()=>runtime.stop());
 runtime.start();
 await assert.rejects(runtime.request('status',{}),/timed out/);
 await runtime.stop();assert.equal(runtime.running,false);
});

test('spawn failure is fully cleaned up and stop remains bounded',async t=>{
 const runtime=new RuntimeSupervisor({executable:'/veyra/does-not-exist',args:[],cwd:process.cwd()});
 t.after(()=>runtime.stop());
 const fatal=once(runtime,'fatal');runtime.start();
 await within(fatal);
 await within(runtime.stop());
 assert.equal(runtime.running,false);
});

test('stop promptly rejects pending commands before terminating the child',async t=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setInterval(()=>{},1000)'],cwd:process.cwd(),requestTimeoutMs:60000});
 t.after(()=>runtime.stop());runtime.start();
 const pending=runtime.request('status',{});
 const stopped=runtime.stop();
 await assert.rejects(within(pending),/stopped/i);
 await stopped;
});

test('concurrent stop calls share one shutdown without writing after stdin ends',async t=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setInterval(()=>{},1000)'],cwd:process.cwd()});
 t.after(()=>runtime.stop());
 const fatals:any[]=[];runtime.on('fatal',error=>fatals.push(error));runtime.start();
 await Promise.all([runtime.stop(),runtime.stop(),runtime.stop()]);
 assert.equal(runtime.running,false);
 assert.equal(fatals.length,0);
});
