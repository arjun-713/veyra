import type {Json} from '../core.ts';

interface PlaybackOptions {
 command:(name:string)=>Promise<Json>;
 onPending:(state:'running'|'paused'|null)=>void;
 onStatus:(status:Json)=>void;
 onError:(error:unknown)=>void;
}

/** Playback requests do not take the app's long-operation lock: Pause can
 * be sent while Start is pending. Only the newest intent updates the UI. */
export class PlaybackControl {
 private request=0;
 private readonly options:PlaybackOptions;
 constructor(options:PlaybackOptions){this.options=options;}
 invalidate():void{this.request++;this.options.onPending(null);}
 async setRunning(running:boolean):Promise<void>{
  const request=++this.request;
  this.options.onPending(running?'running':'paused');
  try{
   const response=await this.options.command(running?'start':'pause');
   if(request===this.request&&response.status)this.options.onStatus(response.status);
  }catch(error){if(request===this.request)this.options.onError(error);}
  finally{if(request===this.request)this.options.onPending(null);}
 }
}
