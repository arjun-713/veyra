import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

test('renderer CSP permits Tauri IPC and event transports',()=>{
 const html=readFileSync(new URL('../index.html',import.meta.url),'utf8');
 assert.match(html,/connect-src[^;]*ipc:\/\/localhost/);
});
