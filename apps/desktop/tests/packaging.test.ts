import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,stat,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {resolveRuntimeLayout,RestartBudget,RotatingLog,validatePackagedBackend} from '../src/packaging.ts';

test('packaged runtime layout uses only the staged backend contract',()=>{
 const layout=resolveRuntimeLayout({resourcesPath:'/opt/Veyra/resources',isPackaged:true,platform:'linux'});
 assert.equal(layout.repo,path.join('/opt/Veyra/resources','backend'));
 assert.equal(layout.python,path.join('/opt/Veyra/resources','backend','python','bin','python3'));
 assert.equal(layout.mapper,path.join('/opt/Veyra/resources','backend','bin','veyra_runtime'));
 assert.equal(layout.manifest,path.join('/opt/Veyra/resources','backend','manifest.json'));
});

test('packaged backend manifests require product identity and version',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'veyra-backend-'));
 const manifest=path.join(root,'manifest.json');
 await writeFile(manifest,JSON.stringify({schema_version:1,product:'veyra',version:'0.1.0',platform:'linux',arch:'x64',files:{}}));
 const layout={repo:root,python:path.join(root,'python','bin','python3'),mapper:path.join(root,'bin','veyra_runtime'),manifest};
 await assert.rejects(validatePackagedBackend(layout,'linux','x64'),/ENOENT/);
});

test('restart budget is bounded and resets after a stable session',()=>{
 const budget=new RestartBudget(3,100);
 assert.deepEqual([budget.next(),budget.next(),budget.next(),budget.next()],[100,200,400,null]);
 budget.reset();assert.equal(budget.next(),100);
});

test('development layout accepts an explicit python and stays platform-safe',()=>{
 const layout=resolveRuntimeLayout({resourcesPath:'unused',isPackaged:false,platform:'win32',repo:'C:\\veyra',python:'C:\\Python\\python.exe'});
 assert.equal(layout.python,'C:\\Python\\python.exe');
 assert.equal(layout.mapper,path.win32.join('C:\\veyra','build','apps','runtime','veyra_runtime.exe'));
});

test('Tauri development uses a dedicated strict Veyra renderer port',async()=>{
 const repository=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..','..','..');
 const tauri=JSON.parse(await readFile(path.join(repository,'src-tauri','tauri.conf.json'),'utf8'));
 const vite=await readFile(path.join(repository,'apps','desktop','vite.renderer.config.ts'),'utf8');
 assert.equal(tauri.build.devUrl,'http://127.0.0.1:1420');
 assert.match(vite,/port:\s*1420/);
 assert.match(vite,/strictPort:\s*true/);
});

test('rotating log serializes concurrent writes and keeps bounded history',async()=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'veyra-log-'));
 const logger=new RotatingLog(path.join(root,'runtime.log'),12,2);
 await Promise.all(['aaaaaa\n','bbbbbb\n','cccccc\n','dddddd\n'].map(line=>logger.write(line)));
 const files=await logger.files();
 assert.ok(files.length<=3);
 assert.ok((await stat(files[0])).size<=19);
 const combined=(await Promise.all(files.map(file=>readFile(file,'utf8')))).join('');
 for(const line of ['bbbbbb','cccccc','dddddd'])assert.match(combined,new RegExp(line));
 assert.doesNotMatch(combined,/aaaaaa/);
});
