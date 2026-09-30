import {test} from 'node:test';
import assert from 'node:assert/strict';
import {pointColor,cellColor} from '../src/renderer/colors.ts';

// The fixed semantic palette must not create garbage for every point in
// an accumulated scan. Reintroducing per-call palette construction breaks
// this allocation contract while preserving the RGB values.
test('semantic canvas coloring reuses RGB storage for repeated classes',()=>{
 const row=new Float32Array(17);row[4]=9;
 const layers={semantic:'ground_truth'};
 const results=new Set();
 for(let i=0;i<10000;i++){
  results.add(pointColor('semantic',row,layers));
  results.add(cellColor('semantic',row));
 }
 assert.equal(results.size,1,'one class needs one shared RGB value, not one allocation per entity');
 assert.deepEqual([...results][0],[.22,.55,.98]);
});
