import {contextBridge,ipcRenderer} from 'electron';
import type {DesktopAPI} from './api';
const api:DesktopAPI={
 info:()=>ipcRenderer.invoke('veyra:info'),
 command:(command,args={})=>ipcRenderer.invoke('veyra:command',command,args),
 configure:config=>ipcRenderer.invoke('veyra:configure',config),
 validateConfig:config=>ipcRenderer.invoke('veyra:validate-config',config),
 chooseDataset:dataset=>ipcRenderer.invoke('veyra:dataset',dataset),
 openConfig:()=>ipcRenderer.invoke('veyra:open-config'),saveConfig:config=>ipcRenderer.invoke('veyra:save-config',config),
 openReport:()=>ipcRenderer.invoke('veyra:open-report'),exportReport:report=>ipcRenderer.invoke('veyra:export-report',report),
 diagnostics:()=>ipcRenderer.invoke('veyra:diagnostics'),screenshot:()=>ipcRenderer.invoke('veyra:screenshot'),
 restart:()=>ipcRenderer.invoke('veyra:restart'),
 onEvent:callback=>{const listener=(_event:Electron.IpcRendererEvent,value:any)=>callback(value);ipcRenderer.on('veyra:event',listener);return()=>ipcRenderer.removeListener('veyra:event',listener);},
 onVisualization:callback=>{const listener=(_event:Electron.IpcRendererEvent,value:any)=>{try{callback(value);}finally{ipcRenderer.send('veyra:visualization-ack');}};ipcRenderer.on('veyra:visualization',listener);return()=>ipcRenderer.removeListener('veyra:visualization',listener);}
};contextBridge.exposeInMainWorld('veyra',api);
