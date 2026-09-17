import type {Json,WireFrame} from './core';

export const nativeRuntimeUnavailableMessage =
 'Veyra desktop runtime bridge is unavailable. Launch Veyra from a supported desktop shell.';

export interface DesktopAPI {
 info():Promise<Json>;
 command(command:string,args?:Json):Promise<Json>;
 configure(config:Json):Promise<Json>;
 validateConfig(config:Json):Promise<Json>;
 chooseDataset(dataset:string):Promise<Json|null>;
 openConfig():Promise<Json|null>;
 saveConfig(config:Json):Promise<boolean>;
 openReport():Promise<Json|null>;
 exportReport(report:Json):Promise<boolean>;
 diagnostics():Promise<Json|boolean>;
 screenshot():Promise<boolean>;
 restart():Promise<Json>;
 onEvent(callback:(event:Json)=>void):()=>void;
 onVisualization(callback:(frame:WireFrame)=>void):()=>void;
}
declare global {interface Window {veyra:DesktopAPI}}
