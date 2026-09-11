import {spawn,type ChildProcessWithoutNullStreams} from 'node:child_process';
import {EventEmitter} from 'node:events';
import {FrameDecoder,validateVisualization,type Json} from './core.ts';
export function terminationTarget(pid:number,platform:NodeJS.Platform=process.platform){return platform==='win32'?pid:-pid;}
function killTree(child:ChildProcessWithoutNullStreams,signal:NodeJS.Signals='SIGTERM'){
 if(!child.pid)return;
 if(process.platform==='win32'){
  spawn('taskkill',['/pid',String(child.pid),'/t','/f'],{stdio:'ignore',windowsHide:true}).unref();return;
 }
 try{process.kill(terminationTarget(child.pid),signal);}catch{try{child.kill(signal);}catch{}}
}
export interface Launch {executable:string;args:string[];cwd:string;requestTimeoutMs?:number}
export class RuntimeSupervisor extends EventEmitter {
 private child:ChildProcessWithoutNullStreams|null=null;
 private pending=new Map<string,{resolve:(v:Json)=>void,reject:(e:Error)=>void,timer:ReturnType<typeof setTimeout>}>();
 private sequence=0; private stopping=false; private fatalReported=false; private launch:Launch;
 private stderr='';
 constructor(launch:Launch){super();this.launch=launch;}
 get running(){return this.child!==null;}
 get pid(){return this.child?.pid??null;}
 get diagnostics(){return this.stderr;}
 start(){
  if(this.child)return;
  this.stopping=false;this.fatalReported=false;this.stderr='';const decoder=new FrameDecoder();
  const child=spawn(this.launch.executable,this.launch.args,{cwd:this.launch.cwd,stdio:'pipe',windowsHide:true,shell:false,detached:process.platform!=='win32'});this.child=child;
  child.stderr.on('data',(chunk:Buffer)=>{this.stderr=(this.stderr+chunk.toString()).slice(-65536);this.emit('log',chunk.toString().slice(-4096));});
  child.stdout.on('data',(chunk:Buffer)=>{
   try{for(const frame of decoder.push(chunk)){
    if(frame.metadata.type==='response'){
     const pending=this.pending.get(String(frame.metadata.id));if(!pending)continue;
     clearTimeout(pending.timer);this.pending.delete(String(frame.metadata.id));
     if(frame.metadata.ok)pending.resolve(frame.metadata);else pending.reject(new Error(frame.metadata.error?.message??'Runtime request failed'));
    }else if(frame.metadata.type==='visualization'){
     validateVisualization(frame.metadata,frame.payload);this.emit('visualization',frame);
    }else this.emit('event',frame.metadata);
   }}catch(error){this.fail(new Error(`Runtime protocol: ${String(error)}`));killTree(child);}
  });
  child.on('error',error=>this.fail(error));
  child.on('exit',(code,signal)=>{if(this.child===child)this.child=null;this.fail(new Error(`Runtime exited (code ${code}, signal ${signal})${this.stderr?'\n'+this.stderr.trim().split('\n').at(-1):''}`),this.stopping);});
 }
 private fail(error:Error,quiet=false){
  for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(error);}this.pending.clear();
  if(!quiet&&!this.fatalReported){this.fatalReported=true;this.emit('event',{type:'status',state:'error',error:{process:'runtime',message:error.message}});this.emit('fatal',error);}
 }
 request(command:string,args:Json={}):Promise<Json>{
  if(!this.child||!this.child.stdin.writable)return Promise.reject(new Error('Runtime is not running'));
  if(this.pending.size>=8)return Promise.reject(new Error('Runtime command queue is full'));
  const id=String(++this.sequence),wire=JSON.stringify({id,command,args})+'\n';
  if(Buffer.byteLength(wire)>65536)return Promise.reject(new Error('Runtime request exceeds 64 KiB'));
  return new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error(`${command} timed out`));},this.launch.requestTimeoutMs??(command==='benchmark'?3600000:120000));
   this.pending.set(id,{resolve,reject,timer});
   this.child!.stdin.write(wire,error=>{if(error){clearTimeout(timer);this.pending.delete(id);reject(error);}});
  });
 }
 async stop(){
  const child=this.child;if(!child)return;this.stopping=true;
  try{child.stdin.write(JSON.stringify({id:'shutdown',command:'shutdown',args:{}})+'\n');child.stdin.end();}catch{}
  await new Promise<void>(resolve=>{
   let timer:ReturnType<typeof setTimeout>;
   const done=()=>{clearTimeout(timer);resolve();};
   child.once('exit',done);timer=setTimeout(()=>{killTree(child);setTimeout(()=>{if(this.child===child)killTree(child,'SIGKILL');},1000).unref();},1000);
   if(child.exitCode!==null)done();
  });this.child=null;
 }
}
