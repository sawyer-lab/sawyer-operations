import test from 'node:test';
import assert from 'node:assert/strict';
import {parseRecording,atTime,stats} from './telemetry.js';

test('receipt time aligns joint, sensor and command data without inventing missing channels',()=>{
  const clock=t=>({monotonic_ns:1e9+t*1e9});
  const rows=[{type:'metadata',schema_version:2,clock:clock(0)},
    {type:'observation',stream:'robot.state',clock:clock(.1),values:{positions:[0,1],velocities:[2],efforts:[3]}},
    {type:'observation',stream:'force_torque',clock:clock(.15),values:{fx:10,tz:-2}},
    {type:'command',stage:'attempted',clock:clock(.2),scheduled_monotonic_ns:1.19e9,run_id:'a',sample_index:0,values:{position:[.5]}},
    {type:'command',stage:'acknowledged',clock:clock(.22),run_id:'a',sample_index:0,values:{}},
    {type:'end',clock:clock(.3)}];
  const data=parseRecording(rows.map(r=>JSON.stringify(r)).join('\n'));
  assert.equal(data.complete,true);assert.equal(data.duration,.3);
  assert.deepEqual(data.tracks.find(t=>t.id==='q0').commanded,[[.2,.5]]);
  assert.deepEqual(data.tracks.find(t=>t.id==='fz').points,[]);
  assert.deepEqual(data.tracks.find(t=>t.id==='fx').points,[[.15,10]]);
  assert.ok(Math.abs(data.tracks.find(t=>t.id==='ack').points[0][1]-20)<1e-8);
  assert.equal(data.tracks.find(t=>t.id==='late').points[0][1],10);
});
test('replay uses previous sample, range statistics retain extrema',()=>{
  const points=[[.1,2],[.2,10],[.3,-2]];
  assert.equal(atTime(points,0),null);
  assert.deepEqual(atTime(points,.2),[.2,10]);
  assert.deepEqual(atTime(points,.29),[.2,10]);
  assert.equal(stats(points,0,.3).max,10);
  assert.equal(stats(points,.3,.4).mean,-2);
  assert.equal(stats(points,.4,1),null);
});
test('invalid and unsupported recordings explain the failure',()=>{
  assert.throws(()=>parseRecording('{'),/line 1/);
  assert.throws(()=>parseRecording('{"type":"metadata","schema_version":1}'),/version 2/);
});
