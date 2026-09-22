"use client";

/* Procedural hero scene: a UGV whose LiDAR sweep crystallizes semantic points
   into adaptive 2.5D cells. All geometry/materials are memoized and shared;
   per-frame work writes preallocated buffers only — no setState, no allocs.
   Cell sizes are exaggerated for legibility (labeled in the HTML overlay). */

import { memo, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

const BANDS = [
  { ring: 6, label: "10 m", cell: 0.9, color: "#33d9f2" },
  { ring: 14, label: "30 m", cell: 1.8, color: "#4dd980" },
  { ring: 24, label: "60 m", cell: 3.0, color: "#ffb340" },
  { ring: 36, label: "100 m", cell: 5.0, color: "#d966d9" },
] as const;

const POINT_CLASSES: Array<[number, number, number]> = [
  [0.16, 0.45, 0.5], // ground / road
  [0.2, 0.7, 0.35], // vegetation
  [1.0, 0.62, 0.2], // vehicle
  [0.72, 0.4, 0.9], // person
  [0.25, 0.85, 0.95], // pole
];

function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Cloud {
  positions: Float32Array;
  baseColors: Float32Array;
  azimuths: Float32Array;
  count: number;
}

function buildCloud(count: number, seed: number): Cloud {
  const rand = mulberry(seed);
  const positions = new Float32Array(count * 3);
  const baseColors = new Float32Array(count * 3);
  const azimuths = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const pick = rand();
    let x = 0;
    let y = 0;
    let z = 0;
    let cls = 0;
    if (pick < 0.62) {
      // Ground scatter across the disc.
      const r = 3 + Math.sqrt(rand()) * 33;
      const a = rand() * Math.PI * 2;
      x = Math.cos(a) * r;
      z = Math.sin(a) * r;
      y = 0.05 + rand() * 0.25;
      cls = 0;
    } else if (pick < 0.78) {
      // Vegetation clumps.
      const cx = (rand() - 0.5) * 44;
      const cz = (rand() - 0.5) * 44;
      x = cx + (rand() - 0.5) * 5;
      z = cz + (rand() - 0.5) * 5;
      y = 0.4 + rand() * 2.4;
      cls = 1;
    } else if (pick < 0.88) {
      // Vehicle block.
      x = 9 + (rand() - 0.5) * 4.4;
      z = -11 + (rand() - 0.5) * 2.2;
      y = 0.3 + rand() * 1.6;
      cls = 2;
    } else if (pick < 0.95) {
      // Pedestrian pair.
      x = -7 + (rand() - 0.5) * 1.4;
      z = 8 + (rand() - 0.5) * 1.4;
      y = 0.2 + rand() * 1.6;
      cls = 3;
    } else {
      // Pole.
      x = -14 + (rand() - 0.5) * 0.6;
      z = -6 + (rand() - 0.5) * 0.6;
      y = 0.2 + rand() * 3.4;
      cls = 4;
    }
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
    azimuths[i] = Math.atan2(z, x);
    const c = POINT_CLASSES[cls];
    baseColors[i * 3] = c[0];
    baseColors[i * 3 + 1] = c[1];
    baseColors[i * 3 + 2] = c[2];
  }
  return { positions, baseColors, azimuths, count };
}

interface CellField {
  matrices: THREE.Matrix4[];
  colors: THREE.Color[];
  count: number;
}

function buildCells(seed: number): CellField {
  const rand = mulberry(seed);
  const matrices: THREE.Matrix4[] = [];
  const colors: THREE.Color[] = [];
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const s = new THREE.Vector3();
  const p = new THREE.Vector3();
  // Concentric bands; inner bands get denser coverage.
  const bands = [
    { inner: 3.5, outer: 6, step: 0.9, density: 0.96, color: BANDS[0].color },
    { inner: 6, outer: 14, step: 1.8, density: 0.88, color: BANDS[1].color },
    { inner: 14, outer: 24, step: 3.0, density: 0.72, color: BANDS[2].color },
    { inner: 24, outer: 36, step: 5.0, density: 0.55, color: BANDS[3].color },
  ];
  for (const band of bands) {
    for (let x = -band.outer; x <= band.outer; x += band.step) {
      for (let z = -band.outer; z <= band.outer; z += band.step) {
        const r = Math.hypot(x, z);
        if (r < band.inner || r > band.outer) continue;
        if (rand() > band.density) continue;
        const h = 0.1 + rand() * 0.22;
        p.set(x, h / 2, z);
        s.set(band.step * 0.92, h, band.step * 0.92);
        m.compose(p, q, s);
        matrices.push(m.clone());
        colors.push(new THREE.Color(band.color).multiplyScalar(0.55 + rand() * 0.3));
      }
    }
  }
  return { matrices, colors, count: matrices.length };
}

const Sweep = memo(function Sweep({ angleRef }: { angleRef: React.MutableRefObject<number> }) {
  const mesh = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.CircleGeometry(37, 48, -0.14, 0.28), []);
  const mat = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: "#62e0d7",
        transparent: true,
        opacity: 0.17,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    []
  );
  useFrame(() => {
    if (mesh.current) mesh.current.rotation.z = -angleRef.current;
  });
  return (
    <mesh ref={mesh} geometry={geo} material={mat} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]} />
  );
});

const Points = memo(function Points({
  cloud,
  angleRef,
  animate,
}: {
  cloud: Cloud;
  angleRef: React.MutableRefObject<number>;
  animate: boolean;
}) {
  const ref = useRef<THREE.Points>(null);
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(cloud.positions, 3));
    const colors = new Float32Array(cloud.baseColors);
    // Start dim; the sweep lights points as it passes.
    for (let i = 0; i < colors.length; i += 1) colors[i] *= 0.22;
    g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return g;
  }, [cloud]);
  const mat = useMemo(
    () => new THREE.PointsMaterial({ size: 0.24, vertexColors: true, sizeAttenuation: true, transparent: true, opacity: 0.95, depthWrite: false }),
    []
  );
  const tick = useRef(0);
  useFrame(() => {
    if (!animate || !ref.current) return;
    tick.current += 1;
    if (tick.current % 2 !== 0) return; // halve buffer-upload cost
    const attr = ref.current.geometry.getAttribute("color") as THREE.BufferAttribute;
    const arr = attr.array as Float32Array;
    const sweep = angleRef.current;
    const { azimuths, baseColors, count } = cloud;
    for (let i = 0; i < count; i += 1) {
      let d = sweep - azimuths[i];
      d = Math.atan2(Math.sin(d), Math.cos(d));
      const lit = d < 0 ? Math.max(0.22, 1 + d / 2.4) : 0.22 + 0.78 * Math.exp(-d * 1.4);
      arr[i * 3] = baseColors[i * 3] * lit;
      arr[i * 3 + 1] = baseColors[i * 3 + 1] * lit;
      arr[i * 3 + 2] = baseColors[i * 3 + 2] * lit;
    }
    attr.needsUpdate = true;
  });
  return <points ref={ref} geometry={geo} material={mat} frustumCulled={false} />;
});

const CellLayer = memo(function CellLayer({ field }: { field: CellField }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const initialized = useRef(false);
  const geo = useMemo(() => new THREE.BoxGeometry(1, 1, 1), []);
  const mat = useMemo(
    () => new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.34, depthWrite: false }),
    []
  );
  useFrame(() => {
    const mesh = ref.current;
    if (!mesh || initialized.current) return;
    initialized.current = true;
    for (let i = 0; i < field.count; i += 1) {
      mesh.setMatrixAt(i, field.matrices[i]);
      mesh.setColorAt(i, field.colors[i]);
    }
    mesh.instanceMatrix.needsUpdate = true;
    const colors = mesh.instanceColor;
    if (colors) colors.needsUpdate = true;
  });
  return <instancedMesh ref={ref} args={[geo, mat, field.count]} frustumCulled={false} />;
});

const Ugv = memo(function Ugv({ angleRef, animate }: { angleRef: React.MutableRefObject<number>; animate: boolean }) {
  const puck = useRef<THREE.Mesh>(null);
  const bodyMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#2a3d4b", roughness: 0.5, metalness: 0.55 }), []);
  const darkMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#0d151d", roughness: 0.8, metalness: 0.3 }), []);
  const puckMat = useMemo(
    () => new THREE.MeshStandardMaterial({ color: "#24333f", roughness: 0.35, metalness: 0.8, emissive: "#62e0d7", emissiveIntensity: 0.55 }),
    []
  );
  const wheelGeo = useMemo(() => new THREE.CylinderGeometry(0.55, 0.55, 0.5, 20), []);
  useFrame((_, delta) => {
    if (!animate) return;
    angleRef.current += delta * 1.5;
    if (puck.current) puck.current.rotation.y = angleRef.current * 2;
  });
  return (
    <group position={[0, 0, 0]} scale={1.15}>
      <mesh material={bodyMat} position={[0, 0.95, 0]}>
        <boxGeometry args={[2.3, 0.85, 3.3]} />
      </mesh>
      {[
        [-1.25, 1.9],
        [1.25, 1.9],
        [-1.25, -1.9],
        [1.25, -1.9],
      ].map(([x, z]) => (
        <mesh key={`${x}${z}`} geometry={wheelGeo} material={darkMat} rotation={[0, 0, Math.PI / 2]} position={[x, 0.55, z]} />
      ))}
      <mesh material={darkMat} position={[0, 1.75, -0.9]}>
        <cylinderGeometry args={[0.09, 0.12, 0.9, 12]} />
      </mesh>
      <mesh ref={puck} material={puckMat} position={[0, 2.35, -0.9]}>
        <cylinderGeometry args={[0.34, 0.34, 0.42, 24]} />
      </mesh>
      <pointLight position={[0, 3.2, -0.9]} intensity={14} distance={16} color="#62e0d7" />
    </group>
  );
});

const Rings = memo(function Rings() {
  const items = useMemo(
    () =>
      BANDS.map((band) => ({
        geo: new THREE.RingGeometry(band.ring - 0.09, band.ring + 0.09, 128),
        mat: new THREE.MeshBasicMaterial({ color: band.color, transparent: true, opacity: 0.4, side: THREE.DoubleSide, depthWrite: false }),
      })),
    []
  );
  return (
    <group rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
      {items.map((item, i) => (
        <mesh key={i} geometry={item.geo} material={item.mat} />
      ))}
    </group>
  );
});

function Rig({ angleRef, animate }: { angleRef: React.MutableRefObject<number>; animate: boolean }) {
  // When motion is off, park the sweep at a composed angle and render once.
  useFrame(() => {
    if (!animate) angleRef.current = 0.9;
  });
  return null;
}

export interface HeroSceneProps {
  compact?: boolean;
  animate?: boolean;
  frameloop?: "always" | "never";
}

export default function HeroScene({ compact = false, animate = true, frameloop = "always" }: HeroSceneProps) {
  const angleRef = useRef(0.9);
  const cloud = useMemo(() => buildCloud(compact ? 650 : 1500, 1337), [compact]);
  const field = useMemo(() => buildCells(2026), []);
  const grid = useMemo(() => new THREE.GridHelper(76, 38, 0x1d2f3b, 0x111d26), []);
  return (
    <Canvas
      frameloop={frameloop}
      dpr={compact ? 1 : [1, 1.75]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ position: [27, 21, 31], fov: 40, near: 0.5, far: 220 }}
      aria-hidden="true"
    >
      <color attach="background" args={["#070c12"]} />
      <fog attach="fog" args={["#070c12", 60, 150]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[18, 30, 12]} intensity={1.1} color="#cfe6ef" />
      <primitive object={grid} position={[0, 0, 0]} />
      <Rings />
      <CellLayer field={field} />
      <Points cloud={cloud} angleRef={angleRef} animate={animate} />
      <Sweep angleRef={angleRef} />
      <Ugv angleRef={angleRef} animate={animate} />
      <Rig angleRef={angleRef} animate={animate} />
    </Canvas>
  );
}
