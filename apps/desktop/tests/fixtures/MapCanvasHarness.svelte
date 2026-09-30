<script lang="ts">
 import {tick} from 'svelte';
 import * as THREE from 'three';
 import MapCanvas from '../../src/renderer/MapCanvas.svelte';
 import type {WireFrame} from '../../src/core';

 let frame=$state.raw<WireFrame|null>(null),stats=$state<Record<string,any>>({});
 let accumulate=$state(1),view=$state('orbit'),follow=$state(false),mode=$state('semantic');
 const probe:Record<string,any>=(window as any).canvasProbe={statsCalls:0,frameStatsCalls:0,uploads:[] as number[],creates:0,deletes:0};
 // Observe real Three/WebGL work without replacing the renderer or controls.
 let scene:THREE.Scene,camera:THREE.PerspectiveCamera;
 const add=THREE.Scene.prototype.add,project=THREE.PerspectiveCamera.prototype.updateProjectionMatrix;
 THREE.Scene.prototype.add=function(...objects){scene=this;return add.apply(this,objects);};
 THREE.PerspectiveCamera.prototype.updateProjectionMatrix=function(){camera=this;return project.call(this);};
 Object.defineProperty(probe,'snapshot',{get:()=>{
  const points=scene?.children.find(child=>child instanceof THREE.Points) as THREE.Points;
  const cells=scene?.children.find(child=>child instanceof THREE.InstancedMesh) as THREE.InstancedMesh;
  if(!points||!cells||!camera)return null;
  const position=points.geometry.getAttribute('position') as THREE.BufferAttribute;
  return {points:points.geometry.drawRange.count,cells:cells.count,pointBuffer:position.id,
   pointVersion:position.version,cellVersion:cells.instanceMatrix.version,
   camera:camera.position.toArray(),creates:probe.creates};
 }});
 const gl=WebGL2RenderingContext.prototype;
 const upload=gl.bufferSubData,remove=gl.deleteBuffer,create=gl.createBuffer;
 gl.createBuffer=function(){probe.creates++;return create.call(this);};
 gl.bufferSubData=function(...args:any[]){
  const array=args[2];
  probe.uploads.push((args[4]||array.length-(args[3]||0))*array.BYTES_PER_ELEMENT);
  return (upload as any).apply(this,args);
 };
 gl.deleteBuffer=function(buffer){probe.deletes++;return remove.call(this,buffer);};
 function onStats(value:Record<string,any>){probe.statsCalls++;if('rendered_points' in value)probe.frameStatsCalls++;stats={...stats,...value};}
 const settle=async()=>{await tick();await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);};
 probe.present=async(index:number,count=2,extra:Record<string,any>={})=>{
  const rows=new Float32Array(count*17+17);
  for(let i=0;i<count;i++){rows[i*17]=index+i;rows[i*17+2]=1;rows[i*17+4]=9;}
  rows.set([index,0,1,.1,9,0,1,1,.5],count*17);
  frame={metadata:{generation:1,index,dataset:'fixture',sequence:'00',pose_available:true,
   pose:[1,0,0,index,0,1,0,0,0,0,1,0,0,0,0,1],layers:{semantic:'ground_truth'},
   points:{offset:0,count,stride:68},cells:{offset:count*68,count:1,stride:68},...extra},payload:new Uint8Array(rows.buffer)};
  await settle();return {...probe.snapshot,statsCalls:probe.statsCalls,frameStatsCalls:probe.frameStatsCalls,stats:{...stats}};
 };
 probe.clear=async()=>{frame=null;await settle();};
 probe.settings=async(options:Record<string,any>)=>{
  if(options.accumulate!==undefined)accumulate=options.accumulate;
  if(options.view!==undefined)view=options.view;
  if(options.follow!==undefined)follow=options.follow;
  if(options.mode!==undefined)mode=options.mode;
  await settle();return probe.snapshot;
 };
 probe.settle=settle;
</script>
<MapCanvas {frame} {mode} {accumulate} {view} {follow} showPoints={true} showCells={true} boundaries={false} {onStats}/>
