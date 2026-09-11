import React,{useEffect,useMemo,useRef} from 'react';
import {atTime} from './telemetry.js';
import {clampRange,zoomRange,visiblePoints} from './timeline.js';

export const traceStyles={measured:{color:'#267b68',name:'Measured',dash:''},command:{color:'#c47620',name:'Command sent',dash:'7 4'},error:{color:'#9861b5',name:'Error · measured − sent',dash:'2 3'}};
export const number=x=>Number.isFinite(x)?x.toFixed(5):'—';
export function AnalysisPlot({track,range,setRange,duration,time,seek,cursors,setCursors,selection,setSelection,mode,traces,hover,setHover,onSelect,selected}) {
  const host=useRef(null),drag=useRef(null);
  const series=useMemo(()=>({measured:track.points,command:track.commanded,error:track.error||[]}),[track]);
  const geometry=useMemo(()=>{
    const active=Object.entries(series).filter(([key])=>traces[key]).map(([key,points])=>[key,visiblePoints(points,range)]);
    let low=Infinity,high=-Infinity;
    for(const [,points]of active)for(const [,y]of points){low=Math.min(low,y);high=Math.max(high,y);}
    if(!Number.isFinite(low))return {paths:[],low:null,high:null};
    const pad=Math.max((high-low)*.1,.00001);low-=pad;high+=pad;
    const x=t=>(t-range[0])/(range[1]-range[0])*1000,y=v=>90-(v-low)/(high-low)*80;
    const paths=active.map(([key,points])=>{
      const bins=new Map();for(const p of points){const pixel=Math.floor(x(p[0]));const bin=bins.get(pixel)||[];bin.push(p);bins.set(pixel,bin);}
      const reduced=[];for(const bin of bins.values()){const min=bin.reduce((a,b)=>a[1]<b[1]?a:b),max=bin.reduce((a,b)=>a[1]>b[1]?a:b);reduced.push(...[bin[0],min,max,bin.at(-1)].sort((a,b)=>a[0]-b[0]));}
      let d='';reduced.forEach(([t,v],i)=>{d+=i?(key==='command'?`H${x(t)}V${y(v)}`:`L${x(t)},${y(v)}`):`M${x(t)},${y(v)}`;});
      return {key,d};
    });return {paths,low,high};
  },[series,range,traces]);
  useEffect(()=>{
    const el=host.current;
    const wheel=e=>{e.preventDefault();const r=el.getBoundingClientRect(),fraction=(e.clientX-r.left)/r.width;
      setRange(e.shiftKey?clampRange(range[0]+e.deltaY/600*(range[1]-range[0]),range[1]-range[0],duration):zoomRange(range,range[0]+fraction*(range[1]-range[0]),Math.exp(Math.max(-1,Math.min(1,e.deltaY*.002))),duration));};
    el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);
  },[range,duration,setRange]);
  const position=e=>{const r=host.current.getBoundingClientRect();return Math.max(range[0],Math.min(range[1],range[0]+(e.clientX-r.left)/r.width*(range[1]-range[0])));};
  function down(e){if(e.button!==0)return;onSelect(track.id);e.currentTarget.setPointerCapture(e.pointerId);const t=position(e);drag.current={x:e.clientX,t,range:[...range],mode};if(mode==='select')setSelection([t,t]);else if(mode==='A'||mode==='B')setCursors(c=>({...c,[mode]:t}));else if(mode==='seek')seek(t);}
  function move(e){const t=position(e);setHover(t);if(!drag.current)return;const d=drag.current;
    if(d.mode==='pan')setRange(clampRange(d.range[0]-(e.clientX-d.x)/host.current.getBoundingClientRect().width*(d.range[1]-d.range[0]),d.range[1]-d.range[0],duration));
    else if(d.mode==='select')setSelection([Math.min(d.t,t),Math.max(d.t,t)]);
    else if(d.mode==='A'||d.mode==='B')setCursors(c=>({...c,[d.mode]:t}));else seek(t);
  }
  const pct=t=>(t-range[0])/(range[1]-range[0])*100;
  return <div className={`ax-track ${selected?'selected':''}`}>
    <button className="ax-track-label" onClick={()=>onSelect(track.id)}><b>{track.label}</b><small>{track.group} · {track.unit}</small><span>{number(atTime(track.points,hover??time)?.[1])}</span></button>
    <div className={`ax-plot mode-${mode}`} ref={host} onPointerDown={down} onPointerMove={move} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onPointerLeave={()=>{if(!drag.current)setHover(null);}} onDoubleClick={()=>setRange([0,duration])}>
      <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-label={`${track.group} ${track.label} plot`}>
        {[0,250,500,750,1000].map(x=><line key={x} x1={x} x2={x} y1="0" y2="100" className="ax-grid"/>)}
        {[10,50,90].map(y=><line key={y} x1="0" x2="1000" y1={y} y2={y} className="ax-grid"/>)}
        {geometry.paths.map(({key,d})=><path key={key} d={d} fill="none" stroke={traceStyles[key].color} strokeDasharray={traceStyles[key].dash} strokeWidth="1.6" vectorEffect="non-scaling-stroke"/>)}
      </svg>
      <span className="ax-y top">{number(geometry.high)}</span><span className="ax-y bottom">{number(geometry.low)}</span>
      {selection&&<div className="ax-selection" style={{left:`${Math.max(0,pct(selection[0]))}%`,width:`${Math.max(0,Math.min(100,pct(selection[1]))-Math.max(0,pct(selection[0])))}%`}}/>}
      {[[time,'playhead'],[hover,'hover'],[cursors.A,'A'],[cursors.B,'B']].map(([t,key])=>t!=null&&t>=range[0]&&t<=range[1]&&<div key={key} className={`ax-cursor ${key}`} style={{left:`${pct(t)}%`}}>{['A','B'].includes(key)&&<b>{key}</b>}</div>)}
      {!track.points.length&&!track.commanded.length&&<span className="ax-no-data">No samples recorded</span>}
    </div>
  </div>;
}

export function Overview({data,range,setRange,time}) {
  const host=useRef(null),drag=useRef(null);
  const points=data?.tracks.find(t=>t.id==='q0')?.points||[];
  const duration=data?.duration||1;
  const path=useMemo(()=>{let low=Infinity,high=-Infinity;for(const [,v]of points){low=Math.min(low,v);high=Math.max(high,v);}const stride=Math.max(1,Math.ceil(points.length/1000));return points.filter((_,i)=>i%stride===0).map(([t,v],i)=>`${i?'L':'M'}${t/duration*1000},${32-(v-low)/(high-low||1)*24}`).join(' ');},[points,duration]);
  return <div className="ax-overview" ref={host} onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);const r=e.currentTarget.getBoundingClientRect(),t=(e.clientX-r.left)/r.width*duration;const edge=e.target.dataset.edge;drag.current={x:e.clientX,range:[...range],edge};if(!edge&&(t<range[0]||t>range[1])){const next=clampRange(t-(range[1]-range[0])/2,range[1]-range[0],duration);setRange(next);drag.current.range=next;}}} onPointerMove={e=>{if(!drag.current)return;const d=drag.current,delta=(e.clientX-d.x)/host.current.getBoundingClientRect().width*duration;if(d.edge==='start')setRange([Math.max(0,Math.min(d.range[1]-.0001,d.range[0]+delta)),d.range[1]]);else if(d.edge==='end')setRange([d.range[0],Math.min(duration,Math.max(d.range[0]+.0001,d.range[1]+delta))]);else setRange(clampRange(d.range[0]+delta,d.range[1]-d.range[0],duration));}} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onDoubleClick={()=>setRange([0,duration])}>
    <svg viewBox="0 0 1000 40" preserveAspectRatio="none"><path d={path} fill="none" stroke="#789f95" strokeWidth="1"/></svg>
    <div className="ax-overview-window" style={{left:`${range[0]/duration*100}%`,width:`${(range[1]-range[0])/duration*100}%`}}><i data-edge="start"/><i data-edge="end"/></div><div className="ax-cursor playhead" style={{left:`${time/duration*100}%`}}/>
  </div>;
}
