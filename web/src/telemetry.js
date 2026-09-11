export const colors = ['#61d9c5','#78aaff','#e8ad6b','#b499ff','#f5839a','#c3d96b','#71d3f5'];
export function parseRecording(text) {
  const rows=text.split(/\r?\n/).filter(x=>x.trim()).map((line,i)=>{
    try{return JSON.parse(line);}catch{throw Error(`Invalid JSON on line ${i+1}`);}
  });
  const meta=rows.find(r=>r.type==='metadata');
  if(meta?.schema_version!==2)throw Error('Expected a schema version 2 telemetry recording');
  const origin=meta.clock?.monotonic_ns;
  if(!Number.isFinite(origin))throw Error('Recording has no monotonic clock origin');
  const timed=rows.filter(r=>Number.isFinite(r.clock?.monotonic_ns)).map(r=>({...r,t:(r.clock.monotonic_ns-origin)/1e9})).sort((a,b)=>a.t-b.t);
  const robot=timed.filter(r=>r.type==='observation'&&r.stream==='robot.state');
  const ft=timed.filter(r=>r.type==='observation'&&r.stream==='force_torque');
  const commands=timed.filter(r=>r.type==='command');
  const attempted=commands.filter(r=>r.stage==='attempted');
  const tracks=[];
  for(const [group,field,command,unit] of [['q','positions','position','rad'],['dq','velocities','velocity','rad/s'],['tau','efforts','effort','N·m']]) {
    for(let j=0;j<7;j++)tracks.push({id:`${group}${j}`,group,label:`J${j}`,unit,color:colors[j],
      points:robot.filter(r=>Number.isFinite(r.values[field]?.[j])).map(r=>[r.t,r.values[field][j]]),
      commanded:attempted.filter(r=>Number.isFinite(r.values[command]?.[j])).map(r=>[r.t,r.values[command][j]])});
  }
  for(const [j,axis] of ['fx','fy','fz','tx','ty','tz'].entries())tracks.push({id:axis,group:'FT',label:axis.toUpperCase(),unit:j<3?'N':'N·m',color:colors[j],commanded:[],points:ft.filter(r=>Number.isFinite(r.values[axis])).map(r=>[r.t,r.values[axis]])});
  const sent=new Map(attempted.map(r=>[`${r.run_id}:${r.sample_index}`,r]));
  const latency=commands.filter(r=>r.stage==='acknowledged'&&sent.has(`${r.run_id}:${r.sample_index}`)).map(r=>[r.t,(r.t-sent.get(`${r.run_id}:${r.sample_index}`).t)*1000]);
  tracks.push({id:'ack',group:'Timing',label:'ACK RTT',unit:'ms',color:'#e8ad6b',points:latency,commanded:[]});
  tracks.push({id:'late',group:'Timing',label:'Send lateness',unit:'ms',color:'#b499ff',points:attempted.map(r=>[r.t,(r.clock.monotonic_ns-r.scheduled_monotonic_ns)/1e6]),commanded:[]});
  return {meta,rows:timed,robot,ft,commands,attempted,tracks,duration:Math.max(.001,timed.at(-1)?.t||0),complete:rows.some(r=>r.type==='end')};
}
export function atTime(points,t) {
  let lo=0,hi=points.length;
  while(lo<hi){const m=(lo+hi)>>1;if(points[m][0]<=t)lo=m+1;else hi=m;}
  return lo?points[lo-1]:null;
}
export function stats(points,start,end) {
  let n=0,min=Infinity,max=-Infinity,sum=0,squares=0;
  for(const [t,y] of points)if(t>=start&&t<=end){n++;min=Math.min(min,y);max=Math.max(max,y);sum+=y;squares+=y*y;}
  return n?{n,min,max,mean:sum/n,rms:Math.sqrt(squares/n)}:null;
}
