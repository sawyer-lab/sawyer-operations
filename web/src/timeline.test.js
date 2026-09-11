import test from 'node:test';
import assert from 'node:assert/strict';
import {clampRange,zoomRange,errorSeries,visiblePoints} from './timeline.js';

test('zoom retains time under pointer; panning stays inside recording',()=>{
  assert.deepEqual(zoomRange([2,6],3,.5,10),[2.5,4.5]);
  assert.deepEqual(clampRange(-4,3,10),[0,3]);
  assert.deepEqual(clampRange(9,3,10),[7,10]);
  assert.deepEqual(zoomRange([2,6],3,100,10),[0,10]);
});
test('error compares measured samples with most recent sent command, never future commands',()=>{
  assert.deepEqual(errorSeries([[0,1],[1,5],[2,8],[3,9]],[[.5,3],[2,7]]),[[1,2],[2,1],[3,2]]);
  assert.deepEqual(errorSeries([[1,5]],[]),[]);
});
test('zoomed view retains samples bounding the visible interval',()=>{
  assert.deepEqual(visiblePoints([[0,2],[1,3],[2,4],[3,5]],[1.3,1.7]),[[1,3],[2,4]]);
  assert.deepEqual(visiblePoints([], [0,1]),[]);
});
