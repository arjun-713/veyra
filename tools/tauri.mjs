import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const repository=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const cli=path.join(repository,'apps','desktop','node_modules','.bin',process.platform==='win32'?'tauri.cmd':'tauri');
const result=spawnSync(cli,process.argv.slice(2),{cwd:repository,stdio:'inherit',env:process.env});
if(result.error)throw result.error;
process.exit(result.status??1);
