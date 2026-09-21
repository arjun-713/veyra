import {invoke} from '@tauri-apps/api/core';
import {listen} from '@tauri-apps/api/event';
import {open,save} from '@tauri-apps/plugin-dialog';
import {readTextFile,writeFile,writeTextFile} from '@tauri-apps/plugin-fs';
import type {DesktopAPI} from './api';
import type {Json,WireFrame} from './core';

type Unlisten=(()=>void)|undefined;

async function chooseDirectory():Promise<string>{
 const selected=await open({directory:true,multiple:false,title:'Choose Veyra dataset directory'});
 if(typeof selected!=='string')throw new Error('No dataset directory selected.');
 return selected;
}

async function openJsonFile(title:string):Promise<Json|null>{
 const selected=await open({directory:false,multiple:false,title,filters:[{name:'JSON',extensions:['json']}]});
 if(typeof selected!=='string')return null;
 const text=await readTextFile(selected);
 if(new TextEncoder().encode(text).byteLength>16*1024*1024)throw new Error('File exceeds 16 MiB');
 const value=JSON.parse(text) as Json;
 if(value.map&&typeof value.map==='object')delete value.map.executable;
 return value;
}

async function saveJsonFile(title:string,value:Json):Promise<boolean>{
 const selected=await save({title,defaultPath:`${title.toLowerCase().replaceAll(' ','-')}.json`,filters:[{name:'JSON',extensions:['json']}]});
 if(typeof selected!=='string')return false;
 const text=JSON.stringify(value,null,2)+'\n';
 if(new TextEncoder().encode(text).byteLength>16*1024*1024)throw new Error('Export exceeds 16 MiB');
 await writeTextFile(selected,text);
 return true;
}

async function saveRendererScreenshot():Promise<boolean>{
 const canvas=document.querySelector<HTMLCanvasElement>('.map-stage canvas')??document.querySelector<HTMLCanvasElement>('canvas');
 if(!canvas)throw new Error('The renderer has no canvas to capture yet. Open Live Mapping first.');
 const selected=await save({title:'Save Veyra renderer screenshot',defaultPath:'veyra-map.png',filters:[{name:'PNG',extensions:['png']}]});
 if(typeof selected!=='string')return false;
 const dataUrl=canvas.toDataURL('image/png');
 const encoded=dataUrl.slice(dataUrl.indexOf(',')+1);
 const binary=atob(encoded);
 const bytes=Uint8Array.from(binary,character=>character.charCodeAt(0));
 await writeFile(selected,bytes);
 return true;
}

export interface TauriDesktopAPI extends DesktopAPI{
 openDataset(dataset:string,root:string,sequence?:string):Promise<Json>;
}

export function createTauriAPI():TauriDesktopAPI{
 return {
  info:()=>invoke<Json>('runtime_status').then(status=>({version:'0.1.0',platform:navigator.platform,repo:'tauri',mapper:null,status})),
  command:(command,args={})=>invoke<Json>('runtime_command',{command,args}),
  stop:()=>invoke<Json>('runtime_stop'),
  configure:config=>invoke<Json>('runtime_configure',{config}),
  validateConfig:config=>invoke<Json>('runtime_validate_config',{config}),
  chooseDataset:async dataset=>invoke<Json>('choose_dataset',{dataset,root:await chooseDirectory()}),
  openDataset:(dataset,root,sequence)=>invoke<Json>('open_dataset',{dataset,root,sequence:sequence??null}),
  openConfig:()=>openJsonFile('Open Veyra configuration'),
  saveConfig:config=>saveJsonFile('Veyra configuration',config),
  openReport:()=>openJsonFile('Open Veyra benchmark report'),
  exportReport:report=>saveJsonFile('Veyra benchmark',report),
  diagnostics:async()=>{const value=await invoke<Json>('export_diagnostics');return saveJsonFile('Veyra diagnostics',value);},
  screenshot:saveRendererScreenshot,
  restart:()=>invoke<Json>('runtime_command',{command:'restart',args:{}}),
  onEvent:callback=>subscribe<Json>('veyra://event',callback),
  onVisualization:callback=>subscribe<WireFrame>('veyra://visualization',callback),
 };
}

function subscribe<T>(channel:string,callback:(value:T)=>void):()=>void{
 let unlisten:Unlisten;
 void listen<T>(channel,event=>{
  const value=event.payload as T;
  if(channel.endsWith('visualization')&&value&&typeof value==='object'){
   const frame=value as T & {payload?:number[]|Uint8Array};
   if(Array.isArray(frame.payload))frame.payload=new Uint8Array(frame.payload);
  }
  callback(value);
 }).then(value=>{unlisten=value;});
 return()=>{unlisten?.();};
}

export function installTauriAPI():boolean{
 if(typeof window==='undefined'||!('__TAURI_INTERNALS__' in window))return false;
 window.veyra=createTauriAPI();
 return true;
}
