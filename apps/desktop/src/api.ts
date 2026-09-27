import type {Json,WireFrame} from './core';

export const nativeRuntimeUnavailableMessage =
 'Veyra desktop runtime bridge is unavailable. Launch Veyra from a supported desktop shell.';

export interface DesktopAPI {
 info():Promise<Json>;
  command(command:string,args?:Json):Promise<Json>;
  stop():Promise<Json>;
 configure(config:Json):Promise<Json>;
 validateConfig(config:Json):Promise<Json>;
 chooseDataset(dataset:string):Promise<Json|null>;
 openDataset?(dataset:string,root:string,sequence?:string):Promise<Json>;
 openConfig():Promise<Json|null>;
 saveConfig(config:Json):Promise<boolean>;
 openReport():Promise<Json|null>;
 exportReport(report:Json):Promise<boolean>;
 /** Complete report of the benchmark the runtime just announced; never a partial event summary. */
 loadBenchmarkArtifact(path:string):Promise<Json>;
 diagnostics():Promise<Json|boolean>;
 screenshot():Promise<boolean>;
 restart():Promise<Json>;
 onEvent(callback:(event:Json)=>void):()=>void;
 onVisualization(callback:(frame:WireFrame)=>void):()=>void;
}
declare global {interface Window {veyra:DesktopAPI}}
export function supportsDirectOpen(api:DesktopAPI):boolean{
 return typeof api.openDataset==='function';
}
export interface OpenedDataset {catalog:Json|null;sequence:string;status:Json|null}
export function normalizeOpenDatasetResponse(response:Json):OpenedDataset{
 const catalog=(response.catalog?.result??response.catalog??response.result??null) as Json|null;
 const sequences=Array.isArray(catalog?.sequences)?catalog.sequences as Json[]:[];
 const selected=typeof response.selected_sequence==='string'?response.selected_sequence as string:'';
 const firstOpenable=sequences.find(entry=>typeof entry?.id==='string'&&(entry?.frames??0)>0);
 return {
  catalog,
  sequence:selected||(typeof firstOpenable?.id==='string'?firstOpenable.id as string:''),
  status:(response.configured?.status??response.configured??response.status??null) as Json|null,
 };
}
