import assert from 'node:assert/strict';
import test from 'node:test';
import {safeLocale} from '../src/locale.ts';

test('safeLocale maps the POSIX C locale to a valid browser locale',()=>{
 assert.equal(safeLocale('C'),'en-US');
});

test('safeLocale preserves a valid locale tag',()=>{
 assert.equal(safeLocale('en-IN'),'en-IN');
});

test('safeLocale falls back for malformed locale values',()=>{
 assert.equal(safeLocale('not a locale'),'en-US');
});
