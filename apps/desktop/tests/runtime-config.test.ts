import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LOW_RESOURCE_PRESET, defaultRuntimeConfig, fullSequenceConfig} from '../src/renderer/runtime-config.ts';

test('low-resource runtime config is the persisted desktop default',()=>{
 const config=defaultRuntimeConfig();
 assert.equal(LOW_RESOURCE_PRESET,'LowResource');
 assert.equal(config.preset,LOW_RESOURCE_PRESET);
 assert.deepEqual(config.map,{policy:'distance_lod',resource_profile:'performance',governor_override:'automatic'});
 assert.deepEqual(config.playback,{fps:10,speed:1,frame_limit:30,full_sequence:false});
 assert.deepEqual(config.visualization,{point_budget:15000,cell_budget:10000,update_hz:2,max_in_flight:1});
});

test('full-sequence mode is explicit and keeps low-resource display limits',()=>{
 const config=fullSequenceConfig(defaultRuntimeConfig());
 assert.equal(config.playback.full_sequence,true);
 assert.equal(config.playback.frame_limit,30);
 assert.equal(config.visualization.point_budget,15000);
});
