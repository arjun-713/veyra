import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RuntimeSupervisor,terminationTarget} from '../src/supervisor.ts';

test('forced shutdown addresses the whole Unix runtime process group',()=>{
 assert.equal(terminationTarget(42,'linux'),-42);
 assert.equal(terminationTarget(42,'darwin'),-42);
 assert.equal(terminationTarget(42,'win32'),42);
});

test('supervisor rejects pending commands when backend dies and reports process identity',async()=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setTimeout(()=>process.exit(7),100)'],cwd:process.cwd()});
 const events:any[]=[],fatals:any[]=[];runtime.on('event',e=>events.push(e));runtime.on('fatal',e=>fatals.push(e));runtime.start();
 await assert.rejects(runtime.request('status',{}),/exited/);
 assert.equal(events.at(-1).error.process,'runtime');
 assert.equal(events.at(-1).state,'error');
 assert.equal(fatals.length,1);
});

test('backend status errors remain ordinary events and do not signal a process fatal',async()=>{
 const script=`const m=Buffer.from(JSON.stringify({type:'status',state:'error',error:{process:'perception',message:'model missing'}}));const h=Buffer.alloc(16);h.write('VYRA');h.writeUInt16LE(1,4);h.writeUInt16LE(1,6);h.writeUInt32LE(m.length,8);process.stdout.write(Buffer.concat([h,m]));setInterval(()=>{},1000)`;
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e',script],cwd:process.cwd()});
 const events:any[]=[],fatals:any[]=[];runtime.on('event',e=>events.push(e));runtime.on('fatal',e=>fatals.push(e));
 const status= new Promise<any>((resolve,reject)=>{
  const timeout=setTimeout(()=>reject(new Error('status event timed out')),2000);
  runtime.on('event',event=>{
   if(event.type==='status'&&event.error?.process==='perception'){
    clearTimeout(timeout);resolve(event);
   }
  });
 });
 runtime.start();
 try{
  const event=await status;
  assert.equal(event.error.process,'perception');
  assert.equal(fatals.length,0);
 }finally{await runtime.stop();}
});

test('supervisor bounds pending requests and terminates a silent child',async()=>{
 const runtime=new RuntimeSupervisor({executable:process.execPath,args:['-e','setInterval(()=>{},1000)'],cwd:process.cwd(),requestTimeoutMs:80});
 runtime.start();
 await assert.rejects(runtime.request('status',{}),/timed out/);
 await runtime.stop();assert.equal(runtime.running,false);
});
