<script lang="ts">
 import {onMount,untrack} from 'svelte';
 import * as THREE from 'three';
 import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
 import {pointColor,cellColor,displayPosition} from './colors';
 import {clampRenderCounts} from './dashboard';
 import {ScanHistory,colorInput,ACCUMULATION_POINT_CAPACITY,HISTORY_STRIDE} from './accumulation';
 import {decodePhysicalLayers,type WireFrame,type Json} from '../core';
 let {frame=null,mode='semantic',showPoints=true,showCells=true,boundaries=false,view='orbit',follow=false,accumulate=1,showRings=false,onStats=()=>{},onInspect=()=>{}}=$props<{frame:WireFrame|null;mode:string;showPoints:boolean;showCells:boolean;boundaries:boolean;view:string;follow:boolean;accumulate?:number;showRings?:boolean;onStats?:(value:Json)=>void;onInspect?:(value:Json)=>void}>();
 let host:HTMLDivElement,ready=$state(false),failure=$state('');
 let renderer:THREE.WebGLRenderer,scene:THREE.Scene,camera:THREE.PerspectiveCamera,controls:OrbitControls;
 let points:THREE.Points,mesh:THREE.InstancedMesh,pointGeo:THREE.BufferGeometry,rings:THREE.Group;
 const capacity=100000;
 const pointCapacity=ACCUMULATION_POINT_CAPACITY;
 let position=new Float32Array(pointCapacity*3),colors=new Float32Array(pointCapacity*3),cellData=new Float32Array(0),cellStride=17;
 const history=new ScanHistory(1,pointCapacity);let paintedMode='',paintedLayers='';
 const transform=new THREE.Object3D(),color=new THREE.Color();
 let lastGeneration=-1,lastIndex=-1,inspectionFrame:WireFrame|null=null;
 function update(){
  if(!ready)return;points.visible=showPoints;mesh.visible=showCells;(mesh.material as THREE.MeshBasicMaterial).wireframe=boundaries;
  if(!frame){pointGeo.setDrawRange(0,0);mesh.count=0;inspectionFrame=null;lastGeneration=-1;lastIndex=-1;history.clear();return;}
  const meta=frame.metadata;
  if(meta.generation<lastGeneration||(meta.generation===lastGeneration&&meta.index<lastIndex))return;
  lastGeneration=meta.generation;lastIndex=meta.index;
  const bytes=frame.payload;const data=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const clamped=clampRenderCounts(meta.points.count,meta.cells.count,capacity);
  const pointCount=clamped.points.count,cellCount=clamped.cells.count;
  // v2 frames pack 9 floats/cell, v3 packs 17; normalize to 17 with NaN
  // padding so inspection never fabricates missing evidence.
  cellStride=Math.max(9,Math.round((meta.cells.stride??36)/4));
  const cellRow=new Float32Array(cellStride);
  // Copy the point section into an aligned little-endian view once.
  const wire=new Float32Array(pointCount*17);
  for(let i=0;i<wire.length;i++)wire[i]=data.getFloat32(meta.points.offset+i*4,true);
  const changed=history.push(meta as any,wire,pointCount);
  paintPoints(changed,meta.layers??{});
  cellData=new Float32Array(cellCount*17);inspectionFrame=frame;
  for(let i=0;i<cellCount;i++){
   for(let j=0;j<cellStride;j++)cellRow[j]=data.getFloat32(meta.cells.offset+i*cellStride*4+j*4,true);
   for(let j=0;j<17;j++)cellData[i*17+j]=j<cellStride?cellRow[j]:Number.NaN;
   const size=cellRow[3];
   transform.position.set(...displayPosition(cellRow[0],cellRow[1],cellRow[2]) as [number,number,number]);transform.scale.set(size*.95,.025,size*.95);transform.updateMatrix();mesh.setMatrixAt(i,transform.matrix);
   color.setRGB(...cellColor(mode,cellRow));mesh.setColorAt(i,color);
  }
  mesh.count=cellCount;mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;mesh.computeBoundingSphere();
  onStats({status:'available',source_points:meta.n_points??meta.points.count,source_cells:meta.total_leaves??meta.cells.count,rendered_points:history.pointCount,accumulated_scans:history.frameCount,rendered_cells:cellCount,sampling_active:clamped.truncated||(meta.n_points??0)>pointCount||(meta.total_leaves??0)>cellCount});
  if(follow&&meta.pose?.length===16){const target=new THREE.Vector3(...displayPosition(meta.pose[3],meta.pose[7],meta.pose[11]));const delta=target.clone().sub(controls.target);camera.position.add(delta);controls.target.copy(target);}
  // Range rings sit on the vehicle, through the same world->display mapping.
  if(rings){rings.visible=!!showRings;if(meta.pose?.length===16){const [rx,ry,rz]=displayPosition(meta.pose[3],meta.pose[7],meta.pose[11]);rings.position.set(rx,ry+0.05,rz);}}
 }
 // Rewrites the GPU point buffers from retained history, oldest scan first.
 // Older scans are dimmed so the live scan stays readable inside the cloud.
 function paintPoints(changed:boolean,layers:Record<string,string>){
  const layerKey=JSON.stringify(layers);
  if(!changed&&paintedMode===mode&&paintedLayers===layerKey)return;
  paintedMode=mode;paintedLayers=layerKey;
  const frames=history.list(),scratch=new Float32Array(17);let n=0;
  frames.forEach((scan,age)=>{
   const fade=frames.length>1?.45+.55*(age/(frames.length-1)):1;
   for(let i=0;i<scan.count&&n<pointCapacity;i++,n++){
    const o=i*HISTORY_STRIDE;
    position.set(displayPosition(scan.rows[o],scan.rows[o+1],scan.rows[o+2]),n*3);
    const c=pointColor(mode,colorInput(scan.rows,o,scratch),layers);
    colors[n*3]=c[0]*fade;colors[n*3+1]=c[1]*fade;colors[n*3+2]=c[2]*fade;
   }
  });
  pointGeo.setDrawRange(0,n);
  const pos=pointGeo.getAttribute('position') as THREE.BufferAttribute,col=pointGeo.getAttribute('color') as THREE.BufferAttribute;
  pos.clearUpdateRanges();pos.addUpdateRange(0,n*3);pos.needsUpdate=true;
  col.clearUpdateRanges();col.addUpdateRange(0,n*3);col.needsUpdate=true;
  pointGeo.computeBoundingSphere();
 }
 function roundSprite(){
  const size=64,canvas=document.createElement('canvas');canvas.width=canvas.height=size;
  const ctx=canvas.getContext('2d')!;const g=ctx.createRadialGradient(size/2,size/2,0,size/2,size/2,size/2);
  g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.7,'rgba(255,255,255,1)');g.addColorStop(1,'rgba(255,255,255,0)');
  ctx.fillStyle=g;ctx.fillRect(0,0,size,size);return new THREE.CanvasTexture(canvas);
 }
 $effect(()=>{frame;mode;showPoints;showCells;boundaries;follow;showRings;ready;untrack(update);});
 $effect(()=>{const scans=Math.max(1,Math.round(accumulate));untrack(()=>{history.setWindow(scans);if(ready&&frame)paintPoints(true,frame.metadata.layers??{});});});
 $effect(()=>{if(!ready)return;const target=controls.target.clone();camera.up.set(0,1,0);if(view==='top'){camera.position.copy(target).add(new THREE.Vector3(0,100,.01));}else if(view==='driver'){camera.position.copy(target).add(new THREE.Vector3(0,3,8));}else camera.position.copy(target).add(new THREE.Vector3(-32,25,36));controls.update();});
 onMount(()=>{
  try{
   renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));host.appendChild(renderer.domElement);
   scene=new THREE.Scene();scene.background=new THREE.Color('#0b1219');camera=new THREE.PerspectiveCamera(55,1,.05,3000);camera.position.set(-32,25,36);controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
   scene.add(new THREE.GridHelper(200,40,0x2d4b5e,0x172b39));
   pointGeo=new THREE.BufferGeometry();pointGeo.setAttribute('position',new THREE.BufferAttribute(position,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setAttribute('color',new THREE.BufferAttribute(colors,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setDrawRange(0,0);
   points=new THREE.Points(pointGeo,new THREE.PointsMaterial({size:.09,sizeAttenuation:true,vertexColors:true,map:roundSprite(),alphaTest:.5}));scene.add(points);
   mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshBasicMaterial(),capacity);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.count=0;scene.add(mesh);
   rings=new THREE.Group();
   for(const [radius,color] of [[10,0x33d9f2],[30,0x4dd980],[60,0xffb340],[100,0xd966d9]] as [number,number][]){
    const ring=new THREE.Mesh(new THREE.RingGeometry(radius-0.25,radius+0.25,128),new THREE.MeshBasicMaterial({color,transparent:true,opacity:0.5,side:THREE.DoubleSide}));
    ring.rotation.x=-Math.PI/2;rings.add(ring);
   }
   rings.visible=false;scene.add(rings);
   const resize=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();});resize.observe(host);
   let animation=0,frames=0,last=performance.now(),duration=0;
   const draw=()=>{animation=requestAnimationFrame(draw);const start=performance.now();controls.update();renderer.render(scene,camera);duration+=performance.now()-start;frames++;if(start-last>1000){onStats({fps:frames*1000/(start-last),latency_ms:duration/frames,entities:mesh.count+pointGeo.drawRange.count});last=start;frames=0;duration=0;}};draw();
   const pick=(event:MouseEvent)=>{const rect=host.getBoundingClientRect();const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=ray.intersectObject(mesh)[0];if(hit?.instanceId!==undefined){const r=cellData.subarray(hit.instanceId*17,hit.instanceId*17+17);const num=(i:number)=>Number.isFinite(r[i])?r[i]:null;const size=num(3);const level=size!=null?Math.max(0,Math.min(3,Math.round(Math.log2(size/0.05)))):null;onInspect({x:num(0),y:num(1),elevation:num(2),resolution:size,lod_level:level,semantic_class:num(4),motion:num(5),quality:num(6),drivable_evidence:num(7),utility:num(8),semantic_confidence:num(9),ground_evidence:num(10),terrain_confidence:num(11),geometry_complexity:num(12),point_count:num(13),height_min:num(14),height_max:num(15),height_variance:num(16),physical_layers:inspectionFrame?decodePhysicalLayers(inspectionFrame,hit.instanceId):null});}};
   host.addEventListener('click',pick);
   const lost=(event:Event)=>{event.preventDefault();failure='WebGL context lost. Switch workspace and back, or reload the window to restore rendering — mapping continues in the backend.';onStats({status:'context_lost'});};
   const restored=()=>{failure='';lastGeneration=-1;lastIndex=-1;update();onStats({status:'available'});};
   renderer.domElement.addEventListener('webglcontextlost',lost,false);
   renderer.domElement.addEventListener('webglcontextrestored',restored,false);
   ready=true;onStats({status:'available'});
   return()=>{cancelAnimationFrame(animation);resize.disconnect();host.removeEventListener('click',pick);renderer.domElement.removeEventListener('webglcontextlost',lost);renderer.domElement.removeEventListener('webglcontextrestored',restored);controls.dispose();scene.traverse(obj=>{if(obj instanceof THREE.Mesh||obj instanceof THREE.Points){obj.geometry.dispose();const materials=Array.isArray(obj.material)?obj.material:[obj.material];materials.forEach(m=>m.dispose());}});renderer.dispose();renderer.domElement.remove();};
  }catch(error){failure=String(error);onStats({status:'unavailable',error:failure});}
 });
</script>
<div class="map-canvas" bind:this={host}>{#if failure}<div class="empty"><h2>WebGL unavailable</h2><p>{failure}</p></div>{/if}</div>
<style>.map-canvas{position:absolute;inset:0;overflow:hidden}.empty{padding:3rem;color:#ede8dc}</style>
