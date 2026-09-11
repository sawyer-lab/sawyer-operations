import React, {useEffect, useState} from 'react';

const colors=['#2179ae','#c96042','#57823d','#9763a8','#bb9233','#288a85','#c65f90'];
async function request(path, value) {
  const response=await fetch('/api'+path,value===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.detail || 'Request failed');
  return result;
}

function Plot({samples,index}) {
  const positions=samples.filter(s=>s.position).map(s=>s.position);
  if(!positions.length)return null;
  let lo=Infinity,hi=-Infinity;
  for(const row of positions)for(const value of row){lo=Math.min(lo,value);hi=Math.max(hi,value);}
  const span=hi-lo || 1;
  const stride=Math.max(1,Math.ceil(positions.length/600));
  return <div><svg viewBox="0 0 600 90" role="img" aria-label="Planned joint positions in radians">
    {colors.map((color,j)=><path key={j} fill="none" stroke={color} strokeWidth="1.5" d={positions.map((p,i)=>i%stride===0||i===positions.length-1?`${i===0?'M':'L'}${600*i/Math.max(1,positions.length-1)},${85-(p[j]-lo)/span*80}`:'').join(' ')}/>)}
    <line x1={600*index/Math.max(1,positions.length-1)} x2={600*index/Math.max(1,positions.length-1)} y1="0" y2="90" stroke="#142027"/>
  </svg><div className="plot-legend">Planned position · rad {colors.map((color,i)=><span key={i} style={{color}}>J{i}</span>)}</div></div>;
}

export function OperationsPanel({workspace,recording,recordingError,viewer,previewOnly=false}) {
  const [trajectory,setTrajectory]=useState(null),[index,setIndex]=useState(0),[playing,setPlaying]=useState(false),[loopPreview,setLoopPreview]=useState(false);
  const [error,setError]=useState(''),[files,setFiles]=useState([]),[pending,setPending]=useState(false);
  const [csvMode,setCsvMode]=useState('position'),[rate,setRate]=useState(100);
  const selected=workspace?.selected_trajectory;
  useEffect(()=>{
    let active=true;
    setTrajectory(null);setIndex(0);setPlaying(false);setLoopPreview(false);viewer.current?.setPreview(null);
    if(selected)request('/trajectories/'+selected).then(value=>{if(active){setTrajectory(value);setLoopPreview(true);setPlaying(true);}}).catch(e=>{if(active)setError(e.message);});
    return ()=>{active=false;};
  },[selected]);
  useEffect(()=>{viewer.current?.setPreview(trajectory?.samples[index]?.position || null);},[trajectory,index]);
  useEffect(()=>{
    if(!playing || !trajectory)return;
    let start=performance.now(),initial=index;
    const timer=setInterval(()=>{
      const next=Math.min(trajectory.samples.length-1,initial+Math.floor((performance.now()-start)*trajectory.rate_hz/1000));
      setIndex(next);
      if(next===trajectory.samples.length-1){
        if(loopPreview){start=performance.now();initial=0;setIndex(0);}
        else setPlaying(false);
      }
    },30);
    return ()=>clearInterval(timer);
  },[playing,trajectory,loopPreview]);
  useEffect(()=>{request('/recordings').then(setFiles).catch(e=>setError(e.message));},[workspace?.revision]);
  async function act(fn) {setPending(true);setError('');try{await fn();}catch(e){setError(e.message);}finally{setPending(false);}}
  async function load(file) {
    if(!file)return;
    await act(async()=>{
      const text=await file.text();
      const result=await request(file.name.endsWith('.csv')?'/trajectories/csv':'/trajectories',
        file.name.endsWith('.csv')?{text,name:file.name,mode:csvMode,rate_hz:Number(rate)}:JSON.parse(text));
      if(result.previewable)await request('/preview',{id:result.id});
    });
  }
  return <section className="operations-panel" aria-label="Operations">
    <div className="ops-row"><strong>Trajectories</strong><label className="file-button">Load JSON / CSV<input type="file" accept=".json,.csv" disabled={pending} onChange={e=>{load(e.target.files[0]);e.target.value='';}}/></label>
      <select aria-label="Preview trajectory" value={selected || ''} onChange={e=>act(()=>request('/preview',{id:e.target.value || null}))}>
        <option value="">No preview</option>{workspace?.trajectories?.map(t=><option key={t.id} value={t.id} disabled={!t.previewable}>{t.name} · {t.mode}</option>)}
      </select></div>
    <details><summary>CSV import settings · SI units</summary><div className="ops-row"><label>Mode <select value={csvMode} onChange={e=>setCsvMode(e.target.value)}>{['position','trajectory','velocity','torque'].map(v=><option key={v}>{v}</option>)}</select></label>
      <label>Samples/s <input type="number" min="0.01" value={rate} onChange={e=>setRate(e.target.value)}/></label><small>Columns: position.right_j0 … position.right_j6; likewise velocity, effort, acceleration.</small></div></details>
    {trajectory && <><div className="ops-row"><span>Blue ghost · preview only</span><button onClick={()=>{setLoopPreview(false);if(index===trajectory.samples.length-1)setIndex(0);setPlaying(!playing);}}>{playing?'Pause preview':'Play preview'}</button>
      <span>{(index/trajectory.rate_hz).toFixed(2)} s / {((trajectory.samples.length-1)/trajectory.rate_hz).toFixed(2)} s</span></div>
      <input className="scrubber" aria-label="Preview time" type="range" min="0" max={trajectory.samples.length-1} value={index} onChange={e=>{setLoopPreview(false);setPlaying(false);setIndex(Number(e.target.value));}}/>
      <Plot samples={trajectory.samples} index={index}/></>}
    {!previewOnly && <>
    <div className="ops-row"><strong>Telemetry</strong><button disabled={pending} onClick={()=>act(()=>request(recording?'/recordings/stop':'/recordings',recording?{}:{name:'Workspace recording'}))}>{recording?'Stop & save recording':'Start recording'}</button><span>{recording?`${recording.samples} samples`:'Not recording'}</span></div>
    <details><summary>Saved recordings ({files.length})</summary>{files.map(f=><div key={f.id}><a href={'/api/recordings/'+f.id+'/download'}>{f.name}</a> · {new Date(f.started_at*1000).toLocaleString()}{f.recording?' · recording':''}</div>)}</details>
    </>}
    {(error || recordingError) && <p role="alert" className="command-message error">{error || recordingError}</p>}
  </section>;
}

export function RobotActions() {
  const [error,setError]=useState('');
  async function send(action){setError('');try{await request('/robot/command',{action});}catch(e){setError(e.message);}}
  return <div className="robot-actions"><button className="robot-stop" onClick={()=>send('stop')}>Stop robot</button>
    <details><summary>Enable / disable / reset</summary>{['enable','disable','reset'].map(action=><button key={action} onClick={()=>send(action)}>{action}</button>)}</details>
    <small>Stop requests the bridge’s robot stop. Reset and enable are explicit.</small>{error && <p role="alert">{error}</p>}</div>;
}
