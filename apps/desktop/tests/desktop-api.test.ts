import {test} from 'node:test';
import assert from 'node:assert/strict';
import {normalizeOpenDatasetResponse,supportsDirectOpen} from '../src/api.ts';

test('direct open is advertised only by shells that implement openDataset',()=>{
 assert.equal(supportsDirectOpen({} as any),false);
 assert.equal(supportsDirectOpen({openDataset:async()=>({})} as any),true);
});

test('open_dataset responses normalize across daemon envelope shapes',()=>{
 const catalog={status:'ok',root:'/data',sequences:[{id:'00',frames:10}]};
 const nested=normalizeOpenDatasetResponse({catalog:{result:catalog},selected_sequence:'00',configured:{status:{state:'ready'}}});
 assert.equal(nested.catalog, catalog);
 assert.equal(nested.sequence,'00');
 assert.deepEqual(nested.status,{state:'ready'});
 const flat=normalizeOpenDatasetResponse({catalog,configured:{status:{state:'paused'}},selected_sequence:''});
 assert.equal(flat.sequence,'00');
 assert.deepEqual(flat.status,{state:'paused'});
 const missing=normalizeOpenDatasetResponse({result:catalog});
 assert.equal(missing.sequence,'00');
 assert.equal(missing.status,null);
});
