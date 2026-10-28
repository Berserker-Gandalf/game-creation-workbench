import { t as tr } from './i18n';
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export default function ModelPreview({ url }: { url: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const host = ref.current!;
    setError('');
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setError(tr("当前浏览器不支持 3D 预览")); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
    camera.position.set(3, 2, 3);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x444455, 3));
    const light = new THREE.DirectionalLight(0xffffff, 4); light.position.set(4, 6, 3); scene.add(light);
    const grid = new THREE.GridHelper(10, 20, 0x44464b, 0x292c32); scene.add(grid);
    let disposed = false;
    const manager = new THREE.LoadingManager();
    manager.setURLModifier(value => {
      if (value === url || value.startsWith('blob:') || value.startsWith('data:')) return value;
      throw new Error(tr("仅支持资源内嵌的 GLB，外部文件引用未开放"));
    });
    new GLTFLoader(manager).load(url, gltf => {
      if (disposed) return;
      scene.add(gltf.scene);
      const box = new THREE.Box3().setFromObject(gltf.scene);
      const center = box.getCenter(new THREE.Vector3());
      const size = Math.max(box.getSize(new THREE.Vector3()).length(), 0.1);
      controls.target.copy(center); camera.position.copy(center).add(new THREE.Vector3(size, size * 0.6, size));
      camera.near = size / 1000; camera.far = size * 100; camera.updateProjectionMatrix(); controls.update();
    }, undefined, () => setError(tr("模型无法预览：请使用包含内嵌资源的有效 GLB 文件")));
    const observer = new ResizeObserver(() => {
      const w = host.clientWidth, h = host.clientHeight;
      renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
    }); observer.observe(host);
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
    return () => {
      disposed = true; observer.disconnect(); renderer.setAnimationLoop(null); controls.dispose();
      scene.traverse(obj => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry.dispose();
          for (const material of Array.isArray(obj.material) ? obj.material : [obj.material]) material.dispose();
        }
      });
      renderer.dispose(); renderer.domElement.remove();
    };
  }, [url]);
  return <div className="model-view" ref={ref}>{error && <div className="preview-error">{error}</div>}</div>;
}
