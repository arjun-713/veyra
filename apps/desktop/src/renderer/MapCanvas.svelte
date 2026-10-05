<script lang="ts">
 import {onMount,untrack} from 'svelte';
 import * as THREE from 'three';
 import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
 import {pointColor,cellColor,displayPosition} from './colors';
 import {clampRenderCounts} from './dashboard';
 import {ScanHistory,colorInput,ACCUMULATION_POINT_CAPACITY,HISTORY_STRIDE} from './accumulation';
 import {decodePhysicalLayers,type WireFrame,type Json} from '../core';
 import {inspectorFromRow} from './cell-lookup';
 import {drawableSize,presetPose,worldRowBounds,type Vec3} from './viewport';
 import {createChaseState,observePose,chaseTargets,chaseAlpha,resetChase} from './chase-camera';
 let {frame=null,mode='semantic',showPoints=true,showCells=true,boundaries=false,view='orbit',follow=false,accumulate=1,showRings=false,selectedCell=null,onStats=()=>{},onInspect=()=>{}}=$props<{frame:WireFrame|null;mode:string;showPoints:boolean;showCells:boolean;boundaries:boolean;view:string;follow:boolean;accumulate?:number;showRings?:boolean;selectedCell?:{x:number;y:number;z:number;size:number}|null;onStats?:(value:Json)=>void;onInspect?:(value:Json)=>void}>();
 let host:HTMLDivElement,ready=$state(false),failure=$state('');
 let renderer:THREE.WebGLRenderer,scene:THREE.Scene,camera:THREE.PerspectiveCamera,controls:OrbitControls;
 let points:THREE.Points,mesh:THREE.InstancedMesh,pointGeo:THREE.BufferGeometry,rings:THREE.Group,highlight:THREE.Group;
 const capacity=100000;
 const pointCapacity=ACCUMULATION_POINT_CAPACITY;
 let position=new Float32Array(pointCapacity*3),colors=new Float32Array(pointCapacity*3),cellData=new Float32Array(capacity*17),cellDataCount=0,cellStride=17;
 const history=new ScanHistory(1,pointCapacity);let paintedMode='',paintedLayers='';
 const color=new THREE.Color();let matrices:Float32Array<ArrayBufferLike>=new Float32Array(0),instanceColors:Float32Array<ArrayBufferLike>=new Float32Array(0);
 const littleEndian=new Uint8Array(new Uint32Array([1]).buffer)[0]===1;
 // Reusable per-frame scratch (module scope — never allocated in update()).
 const cellRow=new Float32Array(17),pointScratch=new Float32Array(17);
 const followTarget=new THREE.Vector3(),followDelta=new THREE.Vector3();
 // Driver-view chase camera: pose observed every frame (so switching to
 // driver is instant), eased toward in the draw loop, snapped on reset.
 const chase=createChaseState(),chaseOut=new Float64Array(6),chasePos=new THREE.Vector3(),chaseLook=new THREE.Vector3();let chaseReady=false,chaseSnap=true;
 let lastLayersRef:Record<string,string>|null=null,lastLayerKey='';
 // Payload sections are little-endian float32 at 4-byte offsets: on
 // little-endian hosts one aligned zero-copy view replaces a per-float
 // DataView pass and the old buffer.slice() full copy.
 function readFloats(bytes:Uint8Array,data:DataView,offset:number,count:number):Float32Array{
  const start=bytes.byteOffset+offset;
  if(littleEndian&&start%4===0)return new Float32Array(bytes.buffer,start,count);
  const out=new Float32Array(count);for(let i=0;i<count;i++)out[i]=data.getFloat32(offset+i*4,true);return out;
 }
 function layerKeyFor(layers:Record<string,string>):string{
  if(layers!==lastLayersRef){lastLayersRef=layers;lastLayerKey=`${layers.semantic}|${layers.ground}|${layers.terrain}|${layers.motion}|${layers.utility}`;}
  return lastLayerKey;
 }
 let lastGeneration=-1,lastIndex=-1,inspectionFrame:WireFrame|null=null;
 // Drawable size actually applied to the renderer; 0 until the host has a
 // real layout box. Nothing is rendered before that.
 let width=0,height=0;
 // A camera fit is owed to the first frame of each session (and on mount).
 let fitPending=true,vehicle:Vec3|null=null;
 function resize():boolean{
  const size=drawableSize(host.clientWidth,host.clientHeight);if(!size)return false;
  if(size.width===width&&size.height===height)return true;
  width=size.width;height=size.height;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix();return true;
 }
 // Frames the current map extent for the active preset. Bounds come from the
 // retained cell rows (<=100k), else the live scan: one pass, only on a fit
 // request (first frame, preset change), never per rendered frame.
 function fitView(){
  if(!ready)return;
  // Cells bound the mapped extent even in point-only views; raw scans carry
  // far sparse returns that would zoom the camera out to nothing.
  let bounds=mesh.count>0?worldRowBounds(cellData,mesh.count,17):null;
  if(!bounds){const live=history.list().at(-1);if(live)bounds=worldRowBounds(live.rows,live.count,HISTORY_STRIDE);}
  const t=controls.target;const pose=presetPose(view,bounds,camera.fov,width&&height?width/height:camera.aspect,[t.x,t.y,t.z],vehicle);
  camera.up.set(0,1,0);controls.target.set(...pose.target);camera.position.set(...pose.position);controls.update();
 }
 function update(){
  if(!ready)return;points.visible=showPoints;mesh.visible=showCells;(mesh.material as THREE.MeshBasicMaterial).wireframe=boundaries;
  if(!frame){pointGeo.setDrawRange(0,0);mesh.count=0;cellDataCount=0;inspectionFrame=null;lastGeneration=-1;lastIndex=-1;history.clear();resetChase(chase);chaseReady=false;fitPending=true;vehicle=null;return;}
  const meta=frame.metadata;
  if(meta.generation<lastGeneration||(meta.generation===lastGeneration&&meta.index<lastIndex))return;
  lastGeneration=meta.generation;lastIndex=meta.index;
  const bytes=frame.payload;const data=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const clamped=clampRenderCounts(meta.points.count,meta.cells.count,capacity);
  const pointCount=clamped.points.count,cellCount=clamped.cells.count;
  // v2 frames pack 9 floats/cell, v3 packs 17; normalize to 17 with NaN
  // padding so inspection never fabricates missing evidence.
  cellStride=Math.max(9,Math.round((meta.cells.stride??36)/4));
  // Zero-copy aligned views into the payload (retained by inspectionFrame).
  const wire=readFloats(bytes,data,meta.points.offset,pointCount*17);
  const cells=readFloats(bytes,data,meta.cells.offset,cellCount*cellStride);
  const changed=history.push(meta as any,wire,pointCount);
  paintPoints(changed,meta.layers??{});
  // Rendered instance i, cellData row i, and physical-layer row i share the
  // same ordered payload prefix even when rendering clamps the cell count.
  // cellData is capacity-sized and reused — never allocated per frame.
  cellDataCount=cellCount;inspectionFrame=frame;
  for(let i=0;i<cellCount;i++){
   for(let j=0;j<cellStride;j++)cellRow[j]=cells[i*cellStride+j];
   for(let j=0;j<17;j++)cellData[i*17+j]=j<cellStride?cellRow[j]:Number.NaN;
   const size=cellRow[3];
   // Cells are axis-aligned boxes: write scale + translation straight into
   // the column-major instance matrix instead of composing an Object3D.
   // World (x,y,z) -> display (x,z,-y) inline: no per-cell array alloc.
   const m=matrices,o=i*16;
   m[o]=size*.95;m[o+1]=0;m[o+2]=0;m[o+3]=0;m[o+4]=0;m[o+5]=.025;m[o+6]=0;m[o+7]=0;m[o+8]=0;m[o+9]=0;m[o+10]=size*.95;m[o+11]=0;m[o+12]=cellRow[0];m[o+13]=cellRow[2];m[o+14]=-cellRow[1];m[o+15]=1;
   const [r,g,b]=cellColor(mode,cellRow);color.setRGB(r,g,b);instanceColors[i*3]=color.r;instanceColors[i*3+1]=color.g;instanceColors[i*3+2]=color.b;
  }
  mesh.count=cellCount;
  if(cellCount>0){
   mesh.instanceMatrix.clearUpdateRanges();mesh.instanceMatrix.addUpdateRange(0,cellCount*16);mesh.instanceMatrix.needsUpdate=true;
   mesh.instanceColor!.clearUpdateRanges();mesh.instanceColor!.addUpdateRange(0,cellCount*3);mesh.instanceColor!.needsUpdate=true;
  }
  // Bounds are only needed to raycast a click; Three recomputes them lazily.
  mesh.boundingSphere=null;
  onStats({status:'available',source_points:meta.n_points??meta.points.count,source_cells:meta.total_leaves??meta.cells.count,wire_cells:meta.cells.count,rendered_points:history.pointCount,accumulated_scans:history.frameCount,rendered_cells:cellCount,sampling_active:clamped.truncated||(meta.n_points??0)>pointCount||(meta.total_leaves??0)>cellCount});
  if(meta.pose?.length===16){if(observePose(chase,meta.generation,meta.index,meta.pose))chaseSnap=true;chaseTargets(chase,chaseOut);chasePos.set(chaseOut[0],chaseOut[1],chaseOut[2]);chaseLook.set(chaseOut[3],chaseOut[4],chaseOut[5]);chaseReady=true;}
  if(meta.pose?.length===16)vehicle=displayPosition(meta.pose[3],meta.pose[7],meta.pose[11]) as Vec3;
  if(fitPending&&(cellCount>0||history.pointCount>0)){fitPending=false;fitView();}
  // Driver view chases the vehicle itself; follow only translates other views.
  if(follow&&view!=='driver'&&meta.pose?.length===16){followTarget.set(meta.pose[3],meta.pose[11],-meta.pose[7]);followDelta.subVectors(followTarget,controls.target);camera.position.add(followDelta);controls.target.copy(followTarget);}
  // Range rings sit on the vehicle, through the same world->display mapping.
  if(rings){rings.visible=!!showRings;if(meta.pose?.length===16){rings.position.set(meta.pose[3],meta.pose[11]+0.05,-meta.pose[7]);}}
 }
 // Rewrites the GPU point buffers from retained history, oldest scan first.
 // Older scans are dimmed so the live scan stays readable inside the cloud.
 function paintPoints(changed:boolean,layers:Record<string,string>){
  const layerKey=layerKeyFor(layers);
  if(!changed&&paintedMode===mode&&paintedLayers===layerKey)return;
  paintedMode=mode;paintedLayers=layerKey;
  const frames=history.list();let n=0;
  frames.forEach((scan,age)=>{
   const fade=frames.length>1?.45+.55*(age/(frames.length-1)):1;
   for(let i=0;i<scan.count&&n<pointCapacity;i++,n++){
    const o=i*HISTORY_STRIDE;
    // World (x,y,z) -> display (x,z,-y) inline: no per-point array alloc.
    position[n*3]=scan.rows[o];position[n*3+1]=scan.rows[o+2];position[n*3+2]=-scan.rows[o+1];
    const c=pointColor(mode,colorInput(scan.rows,o,pointScratch),layers);
    colors[n*3]=c[0]*fade;colors[n*3+1]=c[1]*fade;colors[n*3+2]=c[2]*fade;
   }
  });
  pointGeo.setDrawRange(0,n);
  // WebGL2 interprets a zero source length as the whole remaining array,
  // so an empty scan must not upload the two capacity-sized point buffers.
  if(n===0)return;
  const pos=pointGeo.getAttribute('position') as THREE.BufferAttribute,col=pointGeo.getAttribute('color') as THREE.BufferAttribute;
  pos.clearUpdateRanges();pos.addUpdateRange(0,n*3);pos.needsUpdate=true;
  col.clearUpdateRanges();col.addUpdateRange(0,n*3);col.needsUpdate=true;
  // No bounds pass: computeBoundingSphere scans the whole 2M-point buffer
  // (ignoring drawRange) and the map cloud is never frustum culled.
 }
 function roundSprite(){
  const size=64,canvas=document.createElement('canvas');canvas.width=canvas.height=size;
  const ctx=canvas.getContext('2d')!;const g=ctx.createRadialGradient(size/2,size/2,0,size/2,size/2,size/2);
  g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(.7,'rgba(255,255,255,1)');g.addColorStop(1,'rgba(255,255,255,0)');
  ctx.fillStyle=g;ctx.fillRect(0,0,size,size);return new THREE.CanvasTexture(canvas);
 }
 function applyVisibility(){
  if(!ready)return;points.visible=showPoints;mesh.visible=showCells;(mesh.material as THREE.MeshBasicMaterial).wireframe=boundaries;
 }
 $effect(()=>{showPoints;showCells;boundaries;ready;untrack(applyVisibility);});
 $effect(()=>{frame;mode;follow;showRings;ready;untrack(update);});
 $effect(()=>{selectedCell;ready;untrack(paintHighlight);});
 // Selection marker: the inspected cell's flat XY footprint outline plus a
 // short vertical locator line. It marks location only and never implies
 // the 2.5D cell occupies a fabricated volume.
 function paintHighlight(){
  if(!ready||!highlight)return;
  if(!selectedCell||!Number.isFinite(selectedCell.x)||!Number.isFinite(selectedCell.y)||!Number.isFinite(selectedCell.size)||selectedCell.size<=0){highlight.visible=false;return;}
  const z=Number.isFinite(selectedCell.z)?selectedCell.z:0;
  const [hx,hy,hz]=displayPosition(selectedCell.x,selectedCell.y,z);
  const half=selectedCell.size*1.04/2;
  const outline=highlight.children[0] as THREE.LineLoop;
  const positions=outline.geometry.getAttribute('position') as THREE.BufferAttribute;
  positions.setXYZ(0,-half,0,-half);positions.setXYZ(1,half,0,-half);positions.setXYZ(2,half,0,half);positions.setXYZ(3,-half,0,half);positions.needsUpdate=true;
  const locator=highlight.children[1] as THREE.Line;
  const lpos=locator.geometry.getAttribute('position') as THREE.BufferAttribute;
  lpos.setXYZ(0,0,0,0);lpos.setXYZ(1,0,2,0);lpos.needsUpdate=true;
  highlight.position.set(hx,hy,hz);
  highlight.visible=true;
 }
 $effect(()=>{const scans=Math.max(1,Math.round(accumulate));untrack(()=>{history.setWindow(scans);if(ready&&frame)paintPoints(true,frame.metadata.layers??{});});});
 $effect(()=>{view;if(!ready)return;untrack(()=>{if(view==='driver'){chaseSnap=true;if(chaseReady)return;}fitView();});});
 onMount(()=>{
  try{
   renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));
   scene=new THREE.Scene();scene.background=new THREE.Color('#0b1219');camera=new THREE.PerspectiveCamera(55,1,.05,3000);camera.position.set(-32,25,36);
   // Size the drawing buffer to the laid-out host before the canvas is shown
   // or drawn: a first draw at the default 300x150 followed by a resize could
   // leave WebKit presenting an empty canvas until an unrelated repaint.
   resize();host.appendChild(renderer.domElement);
   controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
   scene.add(new THREE.GridHelper(200,40,0x2d4b5e,0x172b39));
   pointGeo=new THREE.BufferGeometry();pointGeo.setAttribute('position',new THREE.BufferAttribute(position,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setAttribute('color',new THREE.BufferAttribute(colors,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setDrawRange(0,0);
   points=new THREE.Points(pointGeo,new THREE.PointsMaterial({size:.09,sizeAttenuation:true,vertexColors:true,map:roundSprite(),alphaTest:.5}));points.frustumCulled=false;scene.add(points);
   mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshBasicMaterial(),capacity);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.frustumCulled=false;
   mesh.instanceColor=new THREE.InstancedBufferAttribute(new Float32Array(capacity*3),3).setUsage(THREE.DynamicDrawUsage);
   matrices=mesh.instanceMatrix.array as Float32Array;instanceColors=mesh.instanceColor.array as Float32Array;mesh.count=0;scene.add(mesh);
   rings=new THREE.Group();
   for(const [radius,color] of [[10,0x33d9f2],[30,0x4dd980],[60,0xffb340],[100,0xd966d9]] as [number,number][]){
    const ring=new THREE.Mesh(new THREE.RingGeometry(radius-0.25,radius+0.25,128),new THREE.MeshBasicMaterial({color,transparent:true,opacity:0.5,side:THREE.DoubleSide}));
    ring.rotation.x=-Math.PI/2;rings.add(ring);
   }
   rings.visible=false;scene.add(rings);
   highlight=new THREE.Group();
   const outlineGeo=new THREE.BufferGeometry();
   outlineGeo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(12),3));
   const outline=new THREE.LineLoop(outlineGeo,new THREE.LineBasicMaterial({color:0xffffff}));
   outline.frustumCulled=false;highlight.add(outline);
   const locatorGeo=new THREE.BufferGeometry();
   locatorGeo.setAttribute('position',new THREE.BufferAttribute(new Float32Array(6),3));
   const locator=new THREE.Line(locatorGeo,new THREE.LineBasicMaterial({color:0xffffff,transparent:true,opacity:0.7}));
   locator.frustumCulled=false;highlight.add(locator);
   highlight.visible=false;highlight.frustumCulled=false;scene.add(highlight);
   // 0x0 reports (hidden/unlaid host) are skipped rather than applied: they
   // would zero the canvas and poison the projection with a NaN aspect.
   const observer=new ResizeObserver(()=>{resize();});observer.observe(host);
   let animation=0,frames=0,last=performance.now(),duration=0,previous=last;
   const draw=()=>{animation=requestAnimationFrame(draw);if(!width&&!resize())return;const start=performance.now();const dt=Math.min(.25,(start-previous)/1000);previous=start;
    if(view==='driver'&&chaseReady){if(chaseSnap){camera.position.copy(chasePos);controls.target.copy(chaseLook);chaseSnap=false;}else{const a=chaseAlpha(dt);camera.position.lerp(chasePos,a);controls.target.lerp(chaseLook,a);}}
    controls.update();renderer.render(scene,camera);duration+=performance.now()-start;frames++;if(start-last>1000){onStats({fps:frames*1000/(start-last),latency_ms:duration/frames,entities:mesh.count+pointGeo.drawRange.count});last=start;frames=0;duration=0;}};draw();
   const pick=(event:MouseEvent)=>{const rect=host.getBoundingClientRect();const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=ray.intersectObject(mesh)[0];if(hit?.instanceId!==undefined&&hit.instanceId<cellDataCount){const inspected=inspectorFromRow(cellData.subarray(hit.instanceId*17,hit.instanceId*17+17));onInspect({...inspected,physical_layers:inspectionFrame?decodePhysicalLayers(inspectionFrame,hit.instanceId):null});}};
   host.addEventListener('click',pick);
   const lost=(event:Event)=>{event.preventDefault();failure='WebGL context lost. Switch workspace and back, or reload the window to restore rendering — mapping continues in the backend.';onStats({status:'context_lost'});};
   const restored=()=>{failure='';lastGeneration=-1;lastIndex=-1;update();onStats({status:'available'});};
   renderer.domElement.addEventListener('webglcontextlost',lost,false);
   renderer.domElement.addEventListener('webglcontextrestored',restored,false);
   ready=true;onStats({status:'available'});
   return()=>{cancelAnimationFrame(animation);observer.disconnect();host.removeEventListener('click',pick);renderer.domElement.removeEventListener('webglcontextlost',lost);renderer.domElement.removeEventListener('webglcontextrestored',restored);controls.dispose();highlight.traverse(obj=>{if(obj instanceof THREE.Line||obj instanceof THREE.LineLoop){obj.geometry.dispose();(obj.material as THREE.Material).dispose();}});scene.traverse(obj=>{if(obj instanceof THREE.Mesh||obj instanceof THREE.Points){obj.geometry.dispose();const materials=Array.isArray(obj.material)?obj.material:[obj.material];materials.forEach(m=>m.dispose());}});renderer.dispose();renderer.domElement.remove();};
  }catch(error){failure=String(error);onStats({status:'unavailable',error:failure});}
 });
</script>
<div class="map-canvas" bind:this={host}>{#if failure}<div class="empty"><h2>WebGL unavailable</h2><p>{failure}</p></div>{/if}</div>
<style>.map-canvas{position:absolute;inset:0;overflow:hidden}.empty{padding:3rem;color:#ede8dc}</style>
