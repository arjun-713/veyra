export type Json = Record<string, any>;
export interface WireFrame { metadata: Json; payload: Uint8Array }
export const policies = ['uniform5','uniform40','distance_lod','utility_lod'] as const;
export const supportedDatasets = ['generic','semanticposs','semantickitti','rellis3d'] as const;
export function isSupportedDataset(value:unknown):value is typeof supportedDatasets[number]{return typeof value==='string'&&supportedDatasets.includes(value as typeof supportedDatasets[number]);}
export function validateCommand(command: unknown, args: unknown = {}): {command:string,args:Json} {
  if (typeof command !== 'string' || !args || typeof args !== 'object' || Array.isArray(args)) throw new Error('Invalid runtime command');
  const value = args as Json;
  const fields: Record<string,string[]> = {start:[],pause:[],step:[],reset:[],status:[],shutdown:[],stop:[],validation:[],replay_close:[],replay_status:[],replay_rate:['fps'],layer:['layer'],seek:['index'],speed:['speed'],sequence:['sequence'],policy:['policy'],governor:['mode'],benchmark:['dataset','sequence','start','count','repetitions','warmup_frames','hardware_profile','force'],replay_open:['path','fps']};
  if (!(command in fields) || Object.keys(value).some(key=>!fields[command].includes(key))) throw new Error('Command or field is not allowed');
  if (command==='seek' && (!Number.isSafeInteger(value.index) || value.index<0)) throw new Error('Invalid frame index');
  if (command==='speed' && (!Number.isFinite(value.speed) || value.speed<0.1 || value.speed>8)) throw new Error('Speed must be 0.1–8');
  if (command==='policy' && !policies.includes(value.policy)) throw new Error('Unknown policy');
  if (command==='layer' && !['semantic','elevation','ground','terrain','traversability','motion','lod','utility'].includes(value.layer)) throw new Error('Unknown layer');
  if (command==='governor' && !['automatic','disabled','conserve'].includes(value.mode)) throw new Error('Unknown governor override');
  if (command==='replay_rate' && ![15,30,60].includes(value.fps)) throw new Error('Replay FPS must be 15, 30 or 60');
  if (command==='sequence' && (typeof value.sequence!=='string' || !/^[\w.-]{1,128}$/.test(value.sequence))) throw new Error('Invalid sequence');
  if (command==='replay_open') {
    if (typeof value.path!=='string' || !value.path || value.path.length>4096) throw new Error('Invalid replay path');
    if ('fps' in value && (!Number.isFinite(value.fps) || value.fps<1 || value.fps>60)) throw new Error('Replay FPS must be 1–60');
  }
  if (command==='benchmark') {
    for (const name of ['start','count','repetitions','warmup_frames']) if(name in value && (!Number.isSafeInteger(value[name]) || value[name]<0 || value[name]>100000)) throw new Error('Invalid benchmark limit');
    for (const name of ['dataset','sequence','hardware_profile']) if(name in value && (typeof value[name]!=='string' || !/^[\w.-]{1,128}$/.test(value[name]))) throw new Error('Invalid benchmark selection');
    if ('force' in value && typeof value.force!=='boolean') throw new Error('Benchmark force must be a boolean');
  }
  return {command,args:value};
}
export class FrameDecoder {
  private buffered = Buffer.alloc(0);
  push(chunk: Uint8Array): WireFrame[] {
    if (chunk.byteLength + this.buffered.length > 40*1024*1024) throw new Error('Protocol buffer limit exceeded');
    this.buffered = Buffer.concat([this.buffered,chunk]);
    const result: WireFrame[]=[];
    while(this.buffered.length>=16) {
      const b=this.buffered;
      if(b.toString('ascii',0,4)!=='VYRA'||b.readUInt16LE(4)!==1) throw new Error('Invalid protocol magic/version');
      const kind=b.readUInt16LE(6),ml=b.readUInt32LE(8),pl=b.readUInt32LE(12);
      if((kind!==1&&kind!==2)||ml>1024*1024||pl>32*1024*1024||(kind===1&&pl!==0)) throw new Error('Protocol length/kind limit exceeded');
      const length=16+ml+pl;if(b.length<length)break;
      const metadata=JSON.parse(b.toString('utf8',16,16+ml));
      if(!metadata || typeof metadata!=='object'||Array.isArray(metadata))throw new Error('Invalid metadata');
      result.push({metadata,payload:new Uint8Array(b.subarray(16+ml,length))});
      this.buffered=b.subarray(length);
    }
    return result;
  }
}
export class RollingTelemetry {
  private samples:Json[]=[]; private capacity:number;
  constructor(capacity=300){if(!Number.isInteger(capacity)||capacity<1||capacity>36000)throw new Error('Invalid history capacity');this.capacity=capacity;}
  push(value:Json){this.samples.push(value);if(this.samples.length>this.capacity)this.samples.splice(0,this.samples.length-this.capacity);}
  values(){return this.samples.slice();}
  series(key:string):(number|null)[]{return this.samples.map(s=>typeof s[key]==='number'&&Number.isFinite(s[key])?s[key]:null);}
}
export function validateVisualization(metadata:Json,payload:Uint8Array){
  for(const key of ['points','cells']){
    const s=metadata[key];
    // v2 cells are 9 floats (36 B); v3 cells carry the full stored evidence
    // (17 floats, 68 B). Points are 17 floats in both versions.
    const expected=key==='points'?[68]:[36,68];
    if(!s||!expected.includes(s.stride))throw new Error('Invalid visualization stride');
    if(!Number.isSafeInteger(s.count)||!Number.isSafeInteger(s.offset)||s.count<0||s.count>100000||s.offset<0||s.offset%4||s.offset+s.count*s.stride>payload.byteLength)throw new Error('Visualization section outside bounds');
  }
  const layer=metadata.physical_layers;
  if(layer!==undefined){
    const end=metadata.cells.offset+metadata.cells.count*metadata.cells.stride;
    if(!layer||layer.version!==1||layer.stride!==60||layer.count!==metadata.cells.count||!Number.isSafeInteger(layer.offset)||layer.offset<end||layer.offset%4||layer.offset+layer.count*60>payload.byteLength)throw new Error('Invalid physical layer section');
  }
}
// Optional section aligned to the sampled cell order: each layer contains
// count, mean, minimum, maximum, population variance. Empty layers have no surface.
export function decodePhysicalLayers(frame:WireFrame,index:number):Json|null{
  const section=frame.metadata.physical_layers;
  if(section===undefined)return null;
  validateVisualization(frame.metadata,frame.payload);
  if(!Number.isSafeInteger(index)||index<0||index>=section.count)throw new Error('Physical layer index outside bounds');
  const view=new DataView(frame.payload.buffer,frame.payload.byteOffset,frame.payload.byteLength);
  const result:Json={};
  ['ground','obstacle','overhead'].forEach((name,i)=>{
    const base=section.offset+index*60+i*20;
    const count=view.getFloat32(base,true);
    const value=(offset:number)=>{const v=view.getFloat32(base+offset,true);return Number.isFinite(count)&&count>0&&Number.isFinite(v)?v:null;};
    result[name]={count:Number.isFinite(count)&&count>=0?count:null,mean:value(4),min:value(8),max:value(12),variance:value(16)};
  });
  return result;
}
// Cell row field indices for the v3 layout (17 floats). v2 rows expose only
// indices 0..8; anything else must render as Unavailable, never fabricated.
export const CELL_V3_FIELDS={x:0,y:1,z:2,size:3,class:4,motion:5,quality:6,drivable:7,utility:8,semanticConfidence:9,groundEvidence:10,terrainConfidence:11,geometryComplexity:12,count:13,zmin:14,zmax:15,zvar:16} as const;
export const CELL_V3_STRIDE=68, CELL_V2_STRIDE=36;
