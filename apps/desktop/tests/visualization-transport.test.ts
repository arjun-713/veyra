import {test} from 'node:test';
import assert from 'node:assert/strict';
import {decodeDesktopVisualization,VisualizationReceiver,createVisualizationSubscription} from '../src/visualization-transport.ts';

function packet(index=0,aligned=true):ArrayBuffer{
 const metadata={type:'visualization',schema_version:3,generation:1,index,points:{offset:0,count:1,stride:68},cells:{offset:68,count:0,stride:68}};
 let json=JSON.stringify(metadata);
 if(aligned)json+=' '.repeat((4-json.length%4)%4);
 const text=new TextEncoder().encode(json),bytes=new Uint8Array(16+text.length+68);
 bytes.set([86,89,82,65]);const head=new DataView(bytes.buffer);
 head.setUint16(4,1,true);head.setUint16(6,2,true);head.setUint32(8,text.length,true);head.setUint32(12,68,true);
 bytes.set(text,16);new DataView(bytes.buffer).setFloat32(16+text.length,42,true);
 return bytes.buffer;
}

test('raw desktop snapshots retain metadata and aligned float support without byte-array JSON',()=>{
 const buffer=packet(4),frame=decodeDesktopVisualization(buffer)!;
 assert.equal(frame.metadata.index,4);
 assert.equal(frame.payload.buffer,buffer);
 assert.equal(frame.payload.byteOffset%4,0);
 assert.equal(new Float32Array(frame.payload.buffer,frame.payload.byteOffset,17)[0],42);
 assert.equal(decodeDesktopVisualization(new ArrayBuffer(0)),null);
});

test('desktop snapshot decoder aligns legacy packets and rejects truncated/corrupt frames',()=>{
 const frame=decodeDesktopVisualization(packet(2,false))!;
 assert.equal(frame.payload.byteOffset%4,0);
 assert.equal(new Float32Array(frame.payload.buffer,frame.payload.byteOffset,17)[0],42);
 const bytes=new Uint8Array(packet());
 assert.throws(()=>decodeDesktopVisualization(bytes.buffer.slice(0,-1)),/length|truncated/i);
 bytes[0]=0;assert.throws(()=>decodeDesktopVisualization(bytes.buffer),/protocol|magic/i);
});

function fixture(){
 const requests:Array<(value:ArrayBuffer)=>void>=[],draws=new Map<number,()=>void>(),indices:number[]=[],errors:unknown[]=[];
 let id=0;
 const receiver=new VisualizationReceiver({
  pull:()=>new Promise(resolve=>requests.push(resolve)),
  schedule:callback=>{draws.set(++id,callback);return id;},cancel:id=>{draws.delete(id);},
  onFrame:frame=>{indices.push(frame.metadata.index);},onError:error=>errors.push(error),
 });
 return {receiver,requests,draws,indices,errors,draw(){const [id,callback]=draws.entries().next().value!;draws.delete(id);callback();}};
}
const settle=()=>new Promise<void>(resolve=>setImmediate(resolve));

test('a slow WebView holds one pull and one snapshot while notifications are coalesced',async()=>{
 const f=fixture();f.receiver.notify();
 for(let i=0;i<488;i++)f.receiver.notify();
 assert.equal(f.requests.length,1);
 f.requests[0](packet(1));await settle();
 assert.equal(f.draws.size,1);assert.equal(f.requests.length,1);assert.deepEqual(f.indices,[]);
 f.draw();assert.deepEqual(f.indices,[1]);assert.equal(f.requests.length,2);
 f.requests[1](packet(487));await settle();f.draw();
 assert.deepEqual(f.indices,[1,487]);assert.equal(f.requests.length,2);
});

test('unsubscribing suppresses late snapshots and cancels pending presentation',async()=>{
 const f=fixture();f.receiver.notify();f.receiver.dispose();f.requests[0](packet(1));await settle();
 assert.equal(f.draws.size,0);assert.deepEqual(f.indices,[]);
 const g=fixture();g.receiver.notify();g.requests[0](packet(2));await settle();g.receiver.dispose();
 assert.equal(g.draws.size,0);assert.deepEqual(g.indices,[]);
});

test('an empty mailbox or rejected pull recovers for a subsequent snapshot',async()=>{
 const f=fixture();f.receiver.notify();f.requests[0](new ArrayBuffer(0));await settle();
 assert.equal(f.draws.size,0);
 f.receiver.notify();f.requests[1](new ArrayBuffer(3));await settle();assert.equal(f.errors.length,1);
 f.receiver.notify();f.requests[2](packet(7));await settle();f.draw();assert.deepEqual(f.indices,[7]);
});

test('desktop subscribers share one native mailbox consumer and unsubscribe independently',async()=>{
 let ready:(()=>void)|undefined,pulls=0,listens=0,stops=0;
 const callbacks:Array<()=>void>=[],first:number[]=[],second:number[]=[];
 const subscribe=createVisualizationSubscription({
  listen:async notify=>{listens++;ready=notify;return ()=>{stops++;};},enable:async()=>{},
  pull:async()=>{pulls++;return packet(pulls);},schedule:callback=>{callbacks.push(callback);return callbacks.length;},cancel:()=>{},
  onError:error=>{throw error;},
 });
 const offFirst=subscribe(frame=>first.push(frame.metadata.index)),offSecond=subscribe(frame=>second.push(frame.metadata.index));
 await settle();assert.equal(listens,1);assert.equal(pulls,1);callbacks.shift()!();
 assert.deepEqual(first,[1]);assert.deepEqual(second,[1]);
 offFirst();ready!();await settle();callbacks.shift()!();
 assert.deepEqual(first,[1]);assert.deepEqual(second,[1,2]);
 offSecond();assert.equal(stops,1);ready!();await settle();assert.equal(pulls,2);
});
