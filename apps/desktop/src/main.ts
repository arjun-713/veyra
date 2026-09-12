import {app,BrowserWindow,dialog,ipcMain} from 'electron';
import {readFile,writeFile,stat} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {RuntimeSupervisor} from './supervisor';
import {isSupportedDataset,validateCommand,type Json,type WireFrame} from './core';
import {RestartBudget,RotatingLog,resolveRuntimeLayout,validatePackagedBackend} from './packaging';
declare const MAIN_WINDOW_VITE_DEV_SERVER_URL:string;
declare const MAIN_WINDOW_VITE_NAME:string;
let window:BrowserWindow|null=null,runtime:RuntimeSupervisor|null=null,quitting=false;
let selectedRoot:string|null=app.isPackaged?null:(process.env.VEYRA_DATASET_ROOT??null),lastConfig:Json|null=null,lastStatus:Json={state:'unconfigured'},lastTelemetry:Json|null=null;
let visualBusy=false,latestVisual:WireFrame|null=null,uiDropped=0;
const layout=resolveRuntimeLayout({resourcesPath:process.resourcesPath,isPackaged:app.isPackaged,platform:process.platform,repo:path.resolve(__dirname,'../../../..'),python:process.env.VEYRA_PYTHON});
const {repo,python,mapper}=layout;
const logger=new RotatingLog(path.join(app.getPath('userData'),'logs','runtime.log'));
const restartBudget=new RestartBudget();let restartTimer:ReturnType<typeof setTimeout>|null=null,stableTimer:ReturnType<typeof setTimeout>|null=null;
function sendEvent(event:Json){if(event.type==='status')lastStatus={...lastStatus,...event};if(event.type==='telemetry')lastTelemetry=event;if(window&&!window.isDestroyed())window.webContents.send('veyra:event',event);}
function flushVisual(){if(visualBusy||!latestVisual||!window||window.isDestroyed())return;visualBusy=true;window.webContents.send('veyra:visualization',latestVisual);latestVisual=null;}
async function log(message:string){try{await logger.write(message);}catch{}}
function scheduleRecovery(){
 if(quitting||restartTimer)return;const delay=restartBudget.next();if(delay===null){sendEvent({type:'status',state:'error',error:{process:'runtime',message:'Runtime restart limit reached; use Restart after correcting the problem.'}});return;}
 sendEvent({type:'status',state:'recovering',error:{process:'runtime',message:`Runtime stopped; restarting in ${delay} ms.`}});
 restartTimer=setTimeout(()=>{restartTimer=null;void (async()=>{try{await runtime?.stop();await launch();if(lastConfig)await runtime!.request('configure',{config:lastConfig});}catch(error){await runtime?.stop();sendEvent({type:'status',state:'error',error:{process:'runtime',message:String(error)}});scheduleRecovery();}})();},delay);
}
async function launch(){
 if(app.isPackaged)await validatePackagedBackend(layout,process.platform,process.arch);
 runtime=new RuntimeSupervisor({executable:python,args:['-u','-m','runtime','--repo',repo],cwd:repo});
 runtime.on('event',sendEvent);runtime.on('fatal',scheduleRecovery);runtime.on('log',(line:string)=>void log(line));
 runtime.on('visualization',(frame:WireFrame)=>{if(latestVisual)uiDropped++;latestVisual=frame;flushVisual();});runtime.start();
 if(stableTimer)clearTimeout(stableTimer);stableTimer=setTimeout(()=>restartBudget.reset(),30000);stableTimer.unref();
}
function trustedConfig(value:unknown):Json{
 if(!value||typeof value!=='object'||Array.isArray(value)||Buffer.byteLength(JSON.stringify(value))>60000)throw new Error('Configuration must be a JSON object smaller than 60 KiB');
 const config=structuredClone(value) as Json;
 if(!selectedRoot)throw new Error('Choose a dataset directory before configuring the runtime');
 config.dataset_root=selectedRoot;config.map={...(config.map??{}),executable:mapper};return config;
}
async function saveJSON(title:string,value:unknown){const result=await dialog.showSaveDialog(window!,{title,defaultPath:title+'.json',filters:[{name:'JSON',extensions:['json']}]});if(result.canceled||!result.filePath)return false;const text=JSON.stringify(value,null,2);if(Buffer.byteLength(text)>16*1024*1024)throw new Error('Export exceeds 16 MiB');await writeFile(result.filePath,text+'\n');return true;}
async function openJSON(title:string){const selected=await dialog.showOpenDialog(window!,{title,properties:['openFile'],filters:[{name:'JSON',extensions:['json']}]});if(selected.canceled)return null;const file=selected.filePaths[0];if((await stat(file)).size>16*1024*1024)throw new Error('File exceeds 16 MiB');return JSON.parse(await readFile(file,'utf8'));}
function registerIPC(){
 function handler(channel:string,fn:(...args:any[])=>unknown){ipcMain.handle(channel,(event,...args)=>{if(!window||event.sender!==window.webContents||event.senderFrame!==window.webContents.mainFrame)throw new Error('Untrusted IPC sender');return fn(...args);});}
 handler('veyra:info',()=>({version:app.getVersion(),platform:process.platform,repo,mapper,backendBundled:app.isPackaged&&existsSync(mapper),status:lastStatus}));
 handler('veyra:command',async(command,args)=>{const validated=validateCommand(command,args);const response=await runtime!.request(validated.command,validated.args);if(response.status)sendEvent({type:'status',...response.status});return response;});
 handler('veyra:configure',async value=>{const config=trustedConfig(value);const result=await runtime!.request('configure',{config});lastConfig=config;if(result.status)sendEvent({type:'status',...result.status});return result;});
 handler('veyra:validate-config',value=>runtime!.request('config_validate',{config:trustedConfig(value)}));
 handler('veyra:dataset',async dataset=>{if(!isSupportedDataset(dataset))throw new Error('Unsupported dataset');const picked=await dialog.showOpenDialog(window!,{title:'Choose dataset root',properties:['openDirectory']});if(picked.canceled)return null;selectedRoot=picked.filePaths[0];return runtime!.request('datasets',{root:selectedRoot,dataset});});
 handler('veyra:open-config',async()=>{const config=await openJSON('Open configuration');if(config&&typeof config==='object'){delete config.map?.executable;return config;}return null;});
 handler('veyra:save-config',config=>{const value=structuredClone(config);if(value.map)delete value.map.executable;return saveJSON('Veyra configuration',value);});
 handler('veyra:open-report',()=>openJSON('Open benchmark report'));
 handler('veyra:export-report',report=>saveJSON('Veyra benchmark',report));
 handler('veyra:diagnostics',()=>saveJSON('Veyra diagnostics',{version:app.getVersion(),platform:process.platform,arch:process.arch,system:os.release(),status:lastStatus,telemetry:lastTelemetry,ui_visualization_dropped:uiDropped,stderr:runtime?.diagnostics}));
 handler('veyra:screenshot',async()=>{const file=await dialog.showSaveDialog(window!,{defaultPath:'veyra-map.png',filters:[{name:'PNG',extensions:['png']}]});if(file.canceled||!file.filePath)return false;const image=await window!.webContents.capturePage();await writeFile(file.filePath,image.toPNG());return true;});
 handler('veyra:restart',async()=>{if(restartTimer){clearTimeout(restartTimer);restartTimer=null;}restartBudget.reset();await runtime?.stop();visualBusy=false;latestVisual=null;await launch();if(lastConfig)return runtime!.request('configure',{config:lastConfig});return {status:{state:'unconfigured'}};});
 ipcMain.on('veyra:visualization-ack',event=>{if(window&&event.sender===window.webContents&&event.senderFrame===window.webContents.mainFrame){visualBusy=false;flushVisual();}});
}
function createWindow(){
 window=new BrowserWindow({width:1600,height:1000,minWidth:1050,minHeight:700,backgroundColor:'#f7f9fc',title:'Veyra',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true,webSecurity:true}});
 window.webContents.setWindowOpenHandler(()=>({action:'deny'}));window.webContents.on('will-navigate',event=>event.preventDefault());
 window.webContents.session.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));
 window.webContents.on('render-process-gone',()=>{visualBusy=false;latestVisual=null;void log('Renderer exited; mapping continues.\n');});
 window.webContents.on('did-finish-load',()=>{visualBusy=false;sendEvent({type:'status',...lastStatus});});
 if(MAIN_WINDOW_VITE_DEV_SERVER_URL)void window.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);else void window.loadFile(path.join(__dirname,`../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
 window.on('closed',()=>{window=null;});
}
app.whenReady().then(async()=>{registerIPC();createWindow();try{await launch();}catch(error){sendEvent({type:'status',state:'error',error:{process:'runtime',message:`Packaged backend validation failed: ${String(error)}`}});}setInterval(()=>{if(!window)return;sendEvent({type:'desktop_telemetry',processes:app.getAppMetrics().map(p=>({name:p.type,pid:p.pid,cpu_percent:p.cpu.percentCPUUsage,rss_bytes:p.memory.workingSetSize*1024})),ui_visualization_dropped:uiDropped});},1000).unref();});
app.on('window-all-closed',()=>{app.quit();});
app.on('before-quit',event=>{if(quitting)return;event.preventDefault();quitting=true;if(restartTimer)clearTimeout(restartTimer);if(stableTimer)clearTimeout(stableTimer);void runtime?.stop().finally(()=>app.quit());});
