import {validateVisualization, type Json, type WireFrame} from '../core.ts';

export function mergeSessionStatus(current:Json,incoming:Json):Json {
 return {...current,...incoming};
}

export function canPlayback(status:Json,busy=false):boolean {
 return !busy && status.frames>0 && ['ready','paused','running','ended'].includes(status.state);
}
export function telemetryFreshness(telemetry:Json,now=Date.now()):string {
 if(typeof telemetry.timestamp!=='number'||!Number.isFinite(telemetry.timestamp))return 'Waiting';
 return telemetry.stale===true||now-telemetry.timestamp*1000>30000?'Stale':'Fresh';
}
// Canonical telemetry age for "STALE · 14.2 s" display. Null when unknown;
// the single freshness clock — do not compute telemetry age elsewhere.
export function telemetryAgeMs(telemetry:Json,now=Date.now()):number|null {
 const t=telemetry.timestamp;
 if(typeof t!=='number'||!Number.isFinite(t))return null;
 const age=now-t*1000;
 if(!Number.isFinite(age)||age<0)return null;
 return age;
}
export function formatTelemetryAge(telemetry:Json,now=Date.now()):string|null {
 const age=telemetryAgeMs(telemetry,now);
 if(age==null)return null;
 if(age<1000)return `${Math.round(age)} ms`;
 return `${(age/1000).toFixed(1)} s`;
}
export function processRss(processes:Json[]):number|null {
 if(!processes.length||processes.some(p=>typeof p.rss_bytes!=='number'||!Number.isFinite(p.rss_bytes)||p.rss_bytes<0))return null;
 return processes.reduce((sum,p)=>sum+p.rss_bytes,0);
}
export function acceptFrame(next:WireFrame,current:WireFrame|null,state?:string,awaiting=false):boolean {
 if(state==='stopped'&&!awaiting)return false;
 if(next.metadata.schema_version!==2&&next.metadata.schema_version!==3)throw new Error('Unsupported visualization schema. Rebuild the desktop and backend together.');
 validateVisualization(next.metadata,next.payload);
 if(next.metadata.cells.offset<next.metadata.points.offset+next.metadata.points.count*next.metadata.points.stride)throw new Error('Visualization sections overlap');
 return !current || next.metadata.generation>=current.metadata.generation;
}
export function diagnosticMessage(event:Json):string|null {
 if(event.type!=='diagnostics')return null;
 const diagnostic=event.diagnostic??{};
 return `${diagnostic.code??'Runtime error'}: ${diagnostic.message??'The runtime rejected an update.'}`;
}
export function validationOutcome(event:Json):string {
 if(event.state==='running')return 'running';
 return event.result?.status==='pass'?'pass':'fail';
}
