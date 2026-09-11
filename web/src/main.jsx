import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { RobotViewer } from './viewer.js';
import { OperationsPanel, RobotActions } from './OperationsPanel.jsx';
import './style.css';
import './operations.css';
import { TelemetryAnalysis } from './TelemetryAnalysis.jsx';

function App() {
  const previewOnly = new URLSearchParams(location.search).get('preview') === '1';
  const host = useRef(null), viewer = useRef(null), latest = useRef(null);
  const [data, setData] = useState(null), [model, setModel] = useState('Loading model…');
  const [pending, setPending] = useState(null), [message, setMessage] = useState(null);
  const [view, setView] = useState('Perspective');
  const [workspace,setWorkspace]=useState(null);
  useEffect(() => {
    let socket, retry, watchdog, disposed = false, received = 0;
    try {
      viewer.current = new RobotViewer(host.current, () => setModel(null), error => setModel(error));
    } catch(error) { setModel(`3D view could not start: ${error.message}`); }
    function connect() {
      socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/live`);
      socket.onmessage = event => {
        received = performance.now();
        const next = JSON.parse(event.data);
        if(next.workspace)setWorkspace(next.workspace);
        latest.current = next;
        viewer.current?.update(next);
        setData(next);
      };
      socket.onclose = () => {
        setData(previous => ({...previous, connected: false}));
        if (!disposed) retry = setTimeout(connect, 1000);
      };
      socket.onerror = () => socket.close();
    }
    connect();
    watchdog = setInterval(() => {
      if (performance.now()-received > 2000) setData(previous => ({...previous, connected: false}));
    }, 1000);
    return () => { disposed = true; clearTimeout(retry); clearInterval(watchdog); socket?.close(); viewer.current?.dispose(); };
  }, []);
  async function command(action) {
    setPending(action); setMessage(null);
    try {
      const response = await fetch('/api/gripper', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Command failed');
      setMessage({text:`${action === 'open' ? 'Open' : 'Close'} command acknowledged.`, error:false});
    } catch(error) { setMessage({text:error.message, error:true}); }
    finally { setPending(null); }
  }
  const live = data?.connected === true;
  const joints = data?.robot?.positions;
  const grip = data?.gripper;
  function chooseView(name) { setView(name); viewer.current?.view(name); }
  return <div className={`app${previewOnly?' preview-only':''}`}>
    <header><a className="brand" href="/" aria-label="Sawyer workspace"><span className="brand-mark">s</span><strong>sawyer<span> / workspace</span></strong></a>
      <div className={`connection ${live?'online':''}`}><i/>{live?'Live connection':'Waiting for robot'}</div>
      <span className="version">HARDWARE WORKSPACE <b>01</b></span></header>
    <main>
      <div className="scene" ref={host} aria-label="Interactive 3D Sawyer robot"/>
      <div className="scene-title"><span className="eyebrow">YOUR ROBOT, IN VIEW</span><h1>Sawyer</h1><p>Move the arm. Watch it here.</p></div>
      <div className="view-switch" aria-label="Camera views">{['Perspective','Front','Top'].map(name=><button key={name} className={view===name?'selected':''} onClick={()=>chooseView(name)}>{name}</button>)}<button onClick={()=>viewer.current?.fit()} title="Fit robot in view" aria-label="Fit robot in view">↗</button></div>
      {model && <div className="model-message" role="status">{model}</div>}
      <aside>
        <RobotActions/>
        <div className="panel-heading"><span className="eyebrow">ROBOT</span><span className="unit">SAWYER / 7 AXES</span></div>
        <h2>Live control</h2>
        <div className="status-row"><span>Arm</span><span className="status-value">{!live?'Disconnected':data.robot.stopped?'Stopped':data.robot.enabled?'Enabled':'Disabled'}</span></div>
        <div className="status-row"><span>Tool plate</span><span className="status-value">{grip?.state || 'Connecting'}</span></div>
        <div className="divider"/>
        <div className="gripper-heading"><h3>Gripper</h3><span>PNEUMATIC</span></div>
        <p className="description">Open or close the physical gripper.</p>
        <div className="gripper-buttons"><button disabled={!!pending} onClick={()=>command('open')}><span className="grip-icon">↤ ↦</span>{pending==='open'?'Opening…':'Open'}</button><button disabled={!!pending} className="primary" onClick={()=>command('close')}><span className="grip-icon">↦ ↤</span>{pending==='close'?'Closing…':'Close'}</button></div>
        <p className="tool-note">{grip?.state === 'down' ? 'The tool reports down. It may need activation on the robot.' : 'Model fingers follow the reported binary grip signal.'}</p>
        {message && <div role="status" className={`command-message ${message.error?'error':''}`}>{message.text}</div>}
        <div className="divider"/>
        <div className="feed-label"><i className={live?'pulse':''}/><span>{live?'Receiving arm state':'No live arm state'}</span><span>30 Hz</span></div>
        <p className="small-note">Head, lights and screen are visual details in this first version.</p>
      </aside>
      <OperationsPanel workspace={workspace} recording={data?.recording} recordingError={data?.recording_error} viewer={viewer} previewOnly={previewOnly}/>
      <div className="scene-hint"><span>Drag to orbit</span><span>Scroll to zoom</span><span>Right-drag to pan</span></div>
      {!live && <div className="offline-note">{data?.robot?'Last received pose · connection lost':'Waiting for live pose · model at rest'}</div>}
    </main>
    <footer><div className="joint-title"><span className="eyebrow">JOINT POSITION</span><small>{live?'Live readings':'Last readings'} · degrees</small></div><div className="joints">{Array.from({length:7},(_,i)=><div className="joint" key={i}><span>J{i}</span><strong>{Number.isFinite(joints?.[i])?(joints[i]*180/Math.PI).toFixed(1):'—'}<small>°</small></strong></div>)}</div><span className="footer-mark">REAL ROBOT<br/>LIVE VIEW</span></footer>
  </div>;
}
const analysis = new URLSearchParams(location.search).get('analysis');
createRoot(document.getElementById('root')).render(analysis ? <TelemetryAnalysis identity={analysis}/> : <App/>);
