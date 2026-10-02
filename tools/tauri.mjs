import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const repository=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
// Invoke the package's JS entrypoint through Node on every platform. Windows
// cannot spawn an npm .cmd shim directly, and shell:true would reinterpret args.
const cli=path.join(repository,'apps','desktop','node_modules','@tauri-apps','cli','tauri.js');
const result=spawnSync(process.execPath,[cli,...process.argv.slice(2)],{cwd:repository,stdio:'inherit',env:process.env});
if(result.error)throw result.error;
process.exit(result.status??1);
