<script lang="ts">
 import {onMount} from 'svelte';
 import * as THREE from 'three';
 import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
 import {pointColor,cellColor,displayPosition,fallbackScene} from './colors';
 import type {WireFrame,Json} from '../core';
 let {frame=null,mode='semantic',showPoints=true,showCells=true,boundaries=false,view='orbit',follow=false,onStats=()=>{},onInspect=()=>{}}=$props<{frame:WireFrame|null;mode:string;showPoints:boolean;showCells:boolean;boundaries:boolean;view:string;follow:boolean;onStats?:(value:Json)=>void;onInspect?:(value:Json)=>void}>();
 let host:HTMLDivElement,ready=$state(false),fallbackNotice=$state('');
 let renderer:THREE.WebGLRenderer,scene:THREE.Scene,camera:THREE.PerspectiveCamera,controls:OrbitControls;
 let points:THREE.Points,mesh:THREE.InstancedMesh,pointGeo:THREE.BufferGeometry;
 let fallbackCanvas:HTMLCanvasElement|null=null,fallbackContext:CanvasRenderingContext2D|null=null;
 const capacity=100000;
 let position=new Float32Array(capacity*3),colors=new Float32Array(capacity*3),cellData=new Float32Array(0);
 const transform=new THREE.Object3D(),color=new THREE.Color();
 let lastGeneration=-1,lastIndex=-1;
 function drawFallback(){
  if(!fallbackCanvas||!fallbackContext)return;
  const width=Math.max(1,host.clientWidth),height=Math.max(1,host.clientHeight),ratio=Math.min(devicePixelRatio||1,2),context=fallbackContext;
  if(fallbackCanvas.width!==Math.round(width*ratio)||fallbackCanvas.height!==Math.round(height*ratio)){fallbackCanvas.width=Math.round(width*ratio);fallbackCanvas.height=Math.round(height*ratio);}
  context.setTransform(ratio,0,0,ratio,0,0);context.fillStyle='#0b1219';context.fillRect(0,0,width,height);
  context.strokeStyle='#172b39';context.lineWidth=1;for(let x=0;x<width;x+=40){context.beginPath();context.moveTo(x,0);context.lineTo(x,height);context.stroke();}for(let y=0;y<height;y+=40){context.beginPath();context.moveTo(0,y);context.lineTo(width,y);context.stroke();}
  const started=performance.now(),fallback=fallbackScene(frame,mode,showPoints,showCells,view),padding=18;
  const spanX=fallback.bounds.maxX-fallback.bounds.minX,spanY=fallback.bounds.maxY-fallback.bounds.minY,scale=Math.min((width-padding*2)/spanX,(height-padding*2)/spanY);
  const offsetX=(width-spanX*scale)/2-fallback.bounds.minX*scale,offsetY=(height-spanY*scale)/2+fallback.bounds.maxY*scale;
  const draw=(kind:'cell'|'point')=>{for(const mark of fallback.marks){if(mark.kind!==kind)continue;const x=offsetX+mark.x*scale,y=offsetY-mark.y*scale;context.fillStyle=mark.color;context.globalAlpha=kind==='cell'?.72:.9;if(kind==='cell'){const size=Math.max(1.5,mark.size*scale);context.fillRect(x-size/2,y-size/2,size,size);if(boundaries){context.strokeStyle='#d5eef055';context.strokeRect(x-size/2,y-size/2,size,size);}}else context.fillRect(x-1,y-1,2,2);}};
  draw('cell');draw('point');context.globalAlpha=1;
  onStats({fps:null,latency_ms:performance.now()-started,entities:fallback.marks.length,renderer:'canvas2d'});
 }
 function update(){
  if(!ready)return;if(fallbackCanvas){drawFallback();return;}points.visible=showPoints;mesh.visible=showCells;(mesh.material as THREE.MeshBasicMaterial).wireframe=boundaries;
  if(!frame){pointGeo.setDrawRange(0,0);mesh.count=0;return;}
  const meta=frame.metadata;
  if(meta.generation<lastGeneration||(meta.generation===lastGeneration&&meta.index<lastIndex))return;
  lastGeneration=meta.generation;lastIndex=meta.index;
  const bytes=frame.payload;const data=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const pointRow=new Float32Array(8),cellRow=new Float32Array(9);
  for(let i=0;i<meta.points.count;i++){
   for(let j=0;j<8;j++)pointRow[j]=data.getFloat32(meta.points.offset+i*32+j*4,true);
   position.set(displayPosition(pointRow[0],pointRow[1],pointRow[2]),i*3);colors.set(pointColor(mode,pointRow,meta.layers??{}),i*3);
  }
  pointGeo.setDrawRange(0,meta.points.count);pointGeo.getAttribute('position').needsUpdate=true;pointGeo.getAttribute('color').needsUpdate=true;pointGeo.computeBoundingSphere();
  cellData=new Float32Array(meta.cells.count*9);
  for(let i=0;i<meta.cells.count;i++){
   for(let j=0;j<9;j++)cellRow[j]=data.getFloat32(meta.cells.offset+i*36+j*4,true);
   cellData.set(cellRow,i*9);transform.position.set(cellRow[1],cellRow[2],-cellRow[0]);transform.scale.set(cellRow[3]*.95,.025,cellRow[3]*.95);transform.updateMatrix();mesh.setMatrixAt(i,transform.matrix);
   color.setRGB(...cellColor(mode,cellRow));mesh.setColorAt(i,color);
  }
  mesh.count=meta.cells.count;mesh.instanceMatrix.needsUpdate=true;if(mesh.instanceColor)mesh.instanceColor.needsUpdate=true;mesh.computeBoundingSphere();
  if(follow&&meta.pose?.length===16){const target=new THREE.Vector3(meta.pose[7],meta.pose[11],-meta.pose[3]);const delta=target.clone().sub(controls.target);camera.position.add(delta);controls.target.copy(target);}
 }
 $effect(()=>{frame;mode;showPoints;showCells;boundaries;follow;ready;update();});
 $effect(()=>{if(!ready)return;if(fallbackCanvas){drawFallback();return;}const target=controls.target.clone();camera.up.set(0,1,0);if(view==='top'){camera.position.copy(target).add(new THREE.Vector3(0,100,.01));}else if(view==='driver'){camera.position.copy(target).add(new THREE.Vector3(0,3,8));}else camera.position.copy(target).add(new THREE.Vector3(-32,25,36));controls.update();});
 onMount(()=>{
  try{
   renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));host.appendChild(renderer.domElement);
   scene=new THREE.Scene();scene.background=new THREE.Color('#0b1219');camera=new THREE.PerspectiveCamera(55,1,.05,3000);camera.position.set(-32,25,36);controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
   scene.add(new THREE.GridHelper(200,40,0x2d4b5e,0x172b39));
   pointGeo=new THREE.BufferGeometry();pointGeo.setAttribute('position',new THREE.BufferAttribute(position,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setAttribute('color',new THREE.BufferAttribute(colors,3).setUsage(THREE.DynamicDrawUsage));pointGeo.setDrawRange(0,0);
   points=new THREE.Points(pointGeo,new THREE.PointsMaterial({size:.1,vertexColors:true}));scene.add(points);
   mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshBasicMaterial(),capacity);mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);mesh.count=0;scene.add(mesh);
   const resize=new ResizeObserver(()=>{const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();});resize.observe(host);
   let animation=0,frames=0,last=performance.now(),duration=0;
   const draw=()=>{animation=requestAnimationFrame(draw);const start=performance.now();controls.update();renderer.render(scene,camera);duration+=performance.now()-start;frames++;if(start-last>1000){onStats({fps:frames*1000/(start-last),latency_ms:duration/frames,entities:mesh.count+pointGeo.drawRange.count});last=start;frames=0;duration=0;}};draw();
   const pick=(event:MouseEvent)=>{const rect=host.getBoundingClientRect();const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1),camera);const hit=ray.intersectObject(mesh)[0];if(hit?.instanceId!==undefined){const r=cellData.subarray(hit.instanceId*9,hit.instanceId*9+9);onInspect({x:r[0],y:r[1],elevation:r[2],resolution:r[3],semantic_class:r[4],motion:r[5],quality:r[6],drivable_evidence:r[7],utility:r[8]});}};
   host.addEventListener('dblclick',pick);ready=true;
   return()=>{cancelAnimationFrame(animation);resize.disconnect();host.removeEventListener('dblclick',pick);controls.dispose();scene.traverse(obj=>{if(obj instanceof THREE.Mesh||obj instanceof THREE.Points){obj.geometry.dispose();const materials=Array.isArray(obj.material)?obj.material:[obj.material];materials.forEach(m=>m.dispose());}});renderer.dispose();renderer.domElement.remove();};
  }catch(error){
   fallbackNotice=`WebGL unavailable · using measured 2D canvas data (${error instanceof Error?error.message:String(error)})`;
   fallbackCanvas=document.createElement('canvas');fallbackCanvas.setAttribute('aria-label','LiDAR and adaptive map 2D fallback');fallbackCanvas.style.width='100%';fallbackCanvas.style.height='100%';fallbackCanvas.style.display='block';host.appendChild(fallbackCanvas);
   fallbackContext=fallbackCanvas.getContext('2d');if(!fallbackContext){fallbackNotice='Visualization unavailable: WebGL and Canvas 2D contexts could not be created.';return;}
   const resize=new ResizeObserver(drawFallback);resize.observe(host);ready=true;
   return()=>{resize.disconnect();fallbackCanvas?.remove();fallbackCanvas=null;fallbackContext=null;};
  }
 });
</script>
<div class="map-canvas" bind:this={host}>{#if fallbackNotice}<div class="fallback-note" role="status">{fallbackNotice}</div>{/if}</div>
<style>.map-canvas{position:absolute;inset:0;overflow:hidden}.fallback-note{position:absolute;left:10px;bottom:10px;z-index:1;max-width:calc(100% - 20px);padding:5px 8px;border:1px solid #355064;border-radius:4px;background:#0c1720d9;color:#91aabd;font-size:9px;line-height:1.35;pointer-events:none}</style>
