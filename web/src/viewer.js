import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export class RobotViewer {
  constructor(host, ready, failure) {
    this.host=host; this.joints=new Map(); this.latest=null; this.closed=false;
    this.scene=new THREE.Scene();
    this.scene.background=new THREE.Color('#dfe4e5');
    this.scene.fog=new THREE.Fog('#dfe4e5',5,12);
    this.camera=new THREE.PerspectiveCamera(34,1,.01,30);
    this.renderer=new THREE.WebGLRenderer({antialias:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));
    this.renderer.shadowMap.enabled=true;
    this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    this.renderer.toneMapping=THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure=1.1;
    host.append(this.renderer.domElement);
    const pmrem=new THREE.PMREMGenerator(this.renderer), room=new RoomEnvironment();
    this.environment=pmrem.fromScene(room,.04); this.scene.environment=this.environment.texture;
    room.dispose(); pmrem.dispose();
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x87949b,2));
    const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(2,4,3);key.castShadow=true;
    key.shadow.mapSize.set(2048,2048);key.shadow.camera.left=-2;key.shadow.camera.right=2;
    key.shadow.camera.top=2;key.shadow.camera.bottom=-2;key.shadow.normalBias=.015;
    this.scene.add(key);
    const floor=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardMaterial({color:0xdfe4e5,roughness:1}));
    floor.rotation.x=-Math.PI/2;floor.position.y=-.003;floor.receiveShadow=true;this.scene.add(floor);
    const grid=new THREE.GridHelper(6,60,0xa9b4b7,0xc8d0d2);grid.position.y=-.002;
    grid.material.transparent=true;grid.material.opacity=.45;this.scene.add(grid);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);
    this.controls.enableDamping=true;this.controls.minDistance=.15;this.controls.maxDistance=8;
    this.view('Perspective');
    this.resize=new ResizeObserver(()=>{
      const {width,height}=host.getBoundingClientRect();
      this.camera.aspect=width/Math.max(height,1);this.camera.updateProjectionMatrix();
      this.renderer.setSize(width,height);
    });this.resize.observe(host);
    new GLTFLoader().load('/models/sawyer.glb',gltf=>{
      if(this.closed)return;
      this.robot=gltf.scene;
      this.robot.traverse(obj=>{
        if(obj.isMesh){obj.castShadow=true;obj.receiveShadow=true;}
        if(obj.userData.joint_name)this.joints.set(obj.userData.joint_name,obj);
      });
      this.scene.add(this.robot);
      this.previewRobot=this.robot.clone(true);this.previewJoints=new Map();
      this.previewRobot.traverse(obj=>{
        if(obj.isMesh){obj.material=new THREE.MeshStandardMaterial({color:0x2c91bd,transparent:true,opacity:.3,depthWrite:false});obj.castShadow=false;}
        if(obj.userData.joint_name)this.previewJoints.set(obj.userData.joint_name,obj);
      });
      this.scene.add(this.previewRobot);this.setPreview(this.previewPosition);
      this.update(this.latest);this.fit();ready();
    },undefined,error=>failure(`Could not load robot model: ${error.message}`));
    this.renderer.setAnimationLoop(()=>{this.controls.update();this.renderer.render(this.scene,this.camera);});
  }
  update(data) {
    this.latest=data;
    if(!data?.robot || !this.robot)return;
    data.robot.positions.forEach((angle,i)=>{
      const joint=this.joints.get(`right_j${i}`);
      if(joint && Number.isFinite(angle))joint.quaternion.setFromAxisAngle(new THREE.Vector3(...joint.userData.joint_axis_gltf),angle);
    });
    const position=data.gripper?.position;
    if(Number.isFinite(position)) {
      const amount=position>0?.006:0;
      for(const name of ['right_gripper_l_finger_joint','right_gripper_r_finger_joint']){
        const joint=this.joints.get(name);
        if(joint)joint.position.copy(new THREE.Vector3(...joint.userData.joint_axis_gltf).multiplyScalar(amount));
      }
    }
  }
  setPreview(positions) {
    this.previewPosition=positions;
    if(!this.previewRobot)return;
    this.previewRobot.visible=!!positions;
    positions?.forEach((angle,i)=>{
      const joint=this.previewJoints.get(`right_j${i}`);
      if(joint && Number.isFinite(angle))joint.quaternion.setFromAxisAngle(new THREE.Vector3(...joint.userData.joint_axis_gltf),angle);
    });
  }
  fit() {
    this.robot?.updateMatrixWorld(true);
    const box=this.robot?new THREE.Box3().setFromObject(this.robot):null;
    const target=box?box.getCenter(new THREE.Vector3()):new THREE.Vector3(0,.45,0);
    const size=box?Math.max(...box.getSize(new THREE.Vector3()).toArray()):1.1;
    this.controls.target.copy(target);
    const direction=this.camera.position.clone().sub(target).normalize();
    this.camera.position.copy(target).addScaledVector(direction,Math.max(1,size)*2.7);
    this.controls.update();
  }
  view(name) {
    const positions={Perspective:[1.6,1.2,1.7],Front:[2.5,.6,0],Top:[.001,3,0]};
    this.camera.position.set(...positions[name]);
    this.controls.target.set(0,.45,0);this.controls.update();
    if(this.robot)this.fit();
  }
  dispose() {
    this.closed=true;this.resize.disconnect();this.controls.dispose();this.renderer.setAnimationLoop(null);
    this.scene.traverse(obj=>{obj.geometry?.dispose();for(const mat of obj.material?Array.isArray(obj.material)?obj.material:[obj.material]:[]){mat.map?.dispose();mat.dispose();}});
    this.environment.dispose();this.renderer.dispose();this.renderer.domElement.remove();
  }
}
