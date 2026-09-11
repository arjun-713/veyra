import {test,expect,_electron as electron} from '@playwright/test';
import {mkdtemp,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

async function genericDataset(){
 const root=await mkdtemp(path.join(os.tmpdir(),'veyra-desktop-e2e-'));
 const points=new Float32Array(800*4),labels=new Uint32Array(800);
 for(let i=0;i<800;i++){const lane=(i%40)-20,row=Math.floor(i/40);points.set([2+row*1.8,lane*.35,.03*Math.sin(i*.3),.5+(i%5)*.1],i*4);labels[i]=Math.abs(lane)<6?1:i%17===0?2:3;}
 const frames=[];
 for(let index=0;index<2;index++){
  const scan=`scan-${index}.bin`,label=`label-${index}.label`;
  await writeFile(path.join(root,scan),Buffer.from(points.buffer));await writeFile(path.join(root,label),Buffer.from(labels.buffer));
  frames.push({sequence:'demo',frame_id:String(index).padStart(6,'0'),timestamp_s:index*.1,pose_sensor_to_world:[[1,0,0,index*.2],[0,1,0,0],[0,0,1,0],[0,0,0,1]],points:{path:scan,format:'xyzi_f32_bin'},labels:{path:label,format:'uint32_label'}});
 }
 await writeFile(path.join(root,'manifest.json'),JSON.stringify({schema_version:1,dataset:'desktop-e2e',point_schema:{format:'xyzi',coordinate_frame:'sensor',intensity_semantics:'normalized'},taxonomy:{version:'e2e-v1',mapping:{'1':9,'2':1}},frames}));return root;
}

test('real labeled replay drives the light dashboard and every product workspace',async()=>{
 const datasetRoot=await genericDataset();
 const app=await electron.launch({args:[path.resolve('.')],env:{...process.env,VEYRA_PYTHON:'/tmp/veyra-product-env/bin/python',VEYRA_DATASET_ROOT:datasetRoot}});
 try{
  const page=await app.firstWindow();const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
  await expect(page.getByRole('heading',{name:'Adaptive 2.5D LiDAR Dashboard'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Raw LiDAR Point Cloud'})).toBeVisible();await expect(page.getByRole('heading',{name:'Semantic LiDAR'})).toBeVisible();await expect(page.getByRole('heading',{name:'Adaptive 2.5D Map'})).toBeVisible();
  expect(await page.evaluate(()=>typeof (window as any).require)).toBe('undefined');expect(await page.evaluate(()=>typeof (window as any).veyra.command)).toBe('function');
  const configured=await page.evaluate(async({datasetRoot})=>window.veyra.configure({dataset:'generic',dataset_root:datasetRoot,sequence:'demo',pipeline:{semantic:{mode:'ground_truth'}},map:{policy:'utility_lod',window_radius_m:100.001},playback:{fps:10,speed:1},visualization:{point_budget:50000,cell_budget:20000,update_hz:15}}),{datasetRoot});
  expect(configured.status.state).toBe('ready');await page.evaluate(()=>window.veyra.command('step'));
  await expect(page.getByText('System Online')).toBeVisible();await expect(page.locator('.visualization-caption').first()).toContainText('Points: 800');await expect(page.locator('.summary-panel')).toContainText('Road');await page.screenshot({path:'test-results/desktop-dashboard.png',fullPage:true});
  await page.getByRole('button',{name:'Live Mapping'}).click();await expect(page.getByRole('heading',{name:'Live Mapping'})).toBeVisible();await page.getByRole('button',{name:'Utility',exact:true}).click();await expect(page.getByText('Utility values are unavailable')).toHaveCount(0);await expect(page.locator('.map-stage canvas')).toBeVisible();
  await page.getByRole('button',{name:'Dashboard'}).click();await page.locator('.dashboard-metric').first().click();await expect(page.getByRole('heading',{name:'Runtime Performance'})).toBeVisible();await expect(page.getByText('Resource governor')).toBeVisible();
  await page.getByRole('button',{name:'Benchmarks'}).click();await expect(page.getByRole('heading',{name:'Policy Benchmarks'})).toBeVisible();await page.getByRole('button',{name:'Datasets'}).click();await expect(page.getByRole('heading',{name:'Dataset Management'})).toBeVisible();await page.getByRole('button',{name:'Settings'}).click();await expect(page.getByLabel('Session configuration JSON')).toBeVisible();
  const unsafe=await page.evaluate(async()=>{try{await window.veyra.command('exec',{shell:'echo unsafe'});return 'accepted';}catch{return 'rejected';}});expect(unsafe).toBe('rejected');expect(errors).toEqual([]);await page.screenshot({path:'test-results/desktop-real-replay.png',fullPage:true});
 }finally{await app.close();}
});
