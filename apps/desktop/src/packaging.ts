import {access,mkdir,readFile,rename,rm,stat,writeFile} from 'node:fs/promises';
import path from 'node:path';

export interface RuntimeLayoutOptions {resourcesPath:string;isPackaged:boolean;platform:NodeJS.Platform;repo?:string;python?:string}
export function resolveRuntimeLayout(options:RuntimeLayoutOptions){
 const pathApi=options.platform==='win32'?path.win32:path.posix;
 const repo=options.isPackaged?pathApi.join(options.resourcesPath,'backend'):(options.repo??process.cwd());
 const executable=options.platform==='win32'?'veyra_runtime.exe':'veyra_runtime';
 const bundledPython=options.platform==='win32'?pathApi.join(repo,'python','python.exe'):pathApi.join(repo,'python','bin','python3');
 return {repo,python:options.python??(options.isPackaged?bundledPython:(options.platform==='win32'?'python':'python3')),mapper:pathApi.join(repo,options.isPackaged?'bin':pathApi.join('build','apps','runtime'),executable),manifest:pathApi.join(repo,'manifest.json')};
}

export class RotatingLog {
 private tail=Promise.resolve();
 private file:string;private maxBytes:number;private backups:number;
 constructor(file:string,maxBytes=1024*1024,backups=3){
  if(!Number.isSafeInteger(maxBytes)||maxBytes<1||!Number.isSafeInteger(backups)||backups<1)throw new Error('Invalid log limits');
  this.file=file;this.maxBytes=maxBytes;this.backups=backups;
 }
 write(message:string){
  const operation=async()=>{
   await mkdir(path.dirname(this.file),{recursive:true});
   let size=0;try{size=(await stat(this.file)).size;}catch{}
   if(size>0&&size+Buffer.byteLength(message)>this.maxBytes){
    await rm(`${this.file}.${this.backups}`,{force:true});
    for(let index=this.backups-1;index>=1;index--){try{await rename(`${this.file}.${index}`,`${this.file}.${index+1}`);}catch{}}
    try{await rename(this.file,`${this.file}.1`);}catch{}
   }
   await writeFile(this.file,message,{flag:'a'});
  };
  this.tail=this.tail.then(operation,operation);return this.tail;
 }
 async files(){
  await this.tail;const result:string[]=[];
  for(const file of [this.file,...Array.from({length:this.backups},(_,i)=>`${this.file}.${i+1}`)]){try{await access(file);result.push(file);}catch{}}
  return result;
 }
}

export async function validatePackagedBackend(layout:ReturnType<typeof resolveRuntimeLayout>,platform:NodeJS.Platform,arch:string){
 const manifest=JSON.parse(await readFile(layout.manifest,'utf8'));
 if(manifest.schema_version!==1||manifest.product!=='veyra'||typeof manifest.version!=='string'||!manifest.version||manifest.platform!==platform||manifest.arch!==arch||!manifest.files||typeof manifest.files!=='object')throw new Error('Backend manifest does not match this application');
 await Promise.all([access(layout.python),access(layout.mapper)]);
 return manifest;
}

export class RestartBudget {
 private attempts=0;
 private limit:number;private baseDelayMs:number;
 constructor(limit=3,baseDelayMs=500){this.limit=limit;this.baseDelayMs=baseDelayMs;}
 next(){if(this.attempts>=this.limit)return null;return this.baseDelayMs*2**this.attempts++;}
 reset(){this.attempts=0;}
}
