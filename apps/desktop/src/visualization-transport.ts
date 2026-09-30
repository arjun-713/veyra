import {validateVisualization,type Json,type WireFrame} from './core.ts';

/** Raw VYRA response from the native latest-snapshot mailbox. Metadata is
 * padded to a four-byte boundary so the renderer can view float32 sections. */
export function decodeDesktopVisualization(buffer:ArrayBuffer):WireFrame|null{
 if(buffer.byteLength===0)return null;
 if(buffer.byteLength<16)throw new Error('Truncated desktop visualization header');
 const bytes=new Uint8Array(buffer),head=new DataView(buffer);
 if(bytes[0]!==86||bytes[1]!==89||bytes[2]!==82||bytes[3]!==65||head.getUint16(4,true)!==1||head.getUint16(6,true)!==2)throw new Error('Invalid desktop visualization protocol');
 const metadataSize=head.getUint32(8,true),payloadSize=head.getUint32(12,true);
 if(metadataSize>1024*1024||payloadSize>32*1024*1024||16+metadataSize+payloadSize!==buffer.byteLength)throw new Error('Invalid desktop visualization length');
 const metadata=JSON.parse(new TextDecoder().decode(bytes.subarray(16,16+metadataSize))) as Json;
 if(!metadata||typeof metadata!=='object'||Array.isArray(metadata)||![2,3].includes(metadata.schema_version))throw new Error('Unsupported desktop visualization schema');
 const offset=16+metadataSize;
 const payload=offset%4===0?bytes.subarray(offset):bytes.slice(offset);
 validateVisualization(metadata,payload);
 return {metadata,payload};
}

interface ReceiverOptions {
 pull:()=>Promise<ArrayBuffer>;
 schedule:(callback:()=>void)=>number;
 cancel:(id:number)=>void;
 onFrame:(frame:WireFrame)=>void;
 onError:(error:unknown)=>void;
}

/** One raw IPC request and one decoded snapshot at most. A busy WebView
 * consumes the newest native snapshot at its next display refresh instead
 * of retaining a queue of multi-megabyte JSON events. */
export class VisualizationReceiver {
 private active=true;
 private requested=false;
 private pulling=false;
 private frame:WireFrame|null=null;
 private animation:number|null=null;
 private readonly options:ReceiverOptions;
 constructor(options:ReceiverOptions){this.options=options;}

 notify():void{if(!this.active)return;this.requested=true;this.pump();}
 dispose():void{
  this.active=false;this.requested=false;this.frame=null;
  if(this.animation!==null)this.options.cancel(this.animation);
  this.animation=null;
 }
 private pump():void{
  if(!this.active||!this.requested||this.pulling||this.frame)return;
  this.requested=false;this.pulling=true;
  void this.options.pull().then(buffer=>{
   if(!this.active)return;
   const frame=decodeDesktopVisualization(buffer);
   if(!frame)return;
   this.frame=frame;
   this.animation=this.options.schedule(()=>{
    this.animation=null;
    const next=this.frame;this.frame=null;
    if(!this.active)return;
    try{if(next)this.options.onFrame(next);}catch(error){this.options.onError(error);}
    this.pump();
   });
  }).catch(error=>{if(this.active)this.options.onError(error);}).finally(()=>{
   this.pulling=false;this.pump();
  });
 }
}

interface SubscriptionOptions extends Omit<ReceiverOptions,'onFrame'> {
 listen:(notify:()=>void)=>Promise<()=>void>;
 enable:()=>Promise<unknown>;
}

/** All API subscribers observe the same snapshot. Only one stream consumes
 * the native mailbox, including diagnostic subscribers alongside the app. */
export function createVisualizationSubscription(options:SubscriptionOptions):(callback:(frame:WireFrame)=>void)=>()=>void{
 const listeners=new Set<(frame:WireFrame)=>void>();
 let stop:(()=>void)|null=null;
 return callback=>{
  listeners.add(callback);
  if(!stop){
   let disposed=false,unlisten:(()=>void)|null=null;
   const receiver=new VisualizationReceiver({...options,onFrame:frame=>{
    for(const listener of listeners){try{listener(frame);}catch(error){options.onError(error);}}
   }});
   stop=()=>{disposed=true;receiver.dispose();unlisten?.();};
   void options.listen(()=>receiver.notify()).then(async detach=>{
    if(disposed){detach();return;}
    unlisten=detach;
    await options.enable();
    if(!disposed)receiver.notify();
   }).catch(error=>{if(!disposed)options.onError(error);});
  }
  return ()=>{
   listeners.delete(callback);
   if(!listeners.size){stop?.();stop=null;}
  };
 };
}
