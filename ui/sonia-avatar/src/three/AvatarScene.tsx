/**
 * AvatarScene — Three.js scene with Sonia's 3D avatar
 *
 * Placeholder geometry: a stylized sphere head with expression-driven
 * morph targets. Will be replaced with a proper VRM/GLB model later.
 *
 * Driven by:
 *   - conversationState -> idle breathing / active animation
 *   - emotion -> material color tint, expression morph
 *   - amplitude -> mouth open amount
 *   - viseme -> lip shape morph targets
 */

import React, { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Environment } from "@react-three/drei";
import * as THREE from "three";
import { useSoniaStore } from "../state/store";

const EMOTION_COLORS: Record<string, string> = {
  neutral: "#cc3333",
  warm: "#e06040",
  stern: "#991111",
  thinking: "#cc6633",
  alert: "#ff4444",
  amused: "#dd5555",
  concerned: "#aa3344",
};

export default function AvatarScene() {
  const meshRef = useRef<THREE.Mesh>(null!);
  const materialRef = useRef<THREE.MeshStandardMaterial>(null!);

  const emotion = useSoniaStore((s) => s.emotion);
  const amplitude = useSoniaStore((s) => s.amplitude);
  const conversationState = useSoniaStore((s) => s.conversationState);

  useFrame((_, delta) => {
    if (!meshRef.current) return;

    // Idle breathing animation
    const t = performance.now() / 1000;
    const breathe = Math.sin(t * 1.5) * 0.02;
    meshRef.current.position.y = breathe;

    // Subtle rotation based on state
    const targetRotY =
      conversationState === "thinking" ? 0.1 :
      conversationState === "listening" ? -0.05 :
      0;
    meshRef.current.rotation.y += (targetRotY - meshRef.current.rotation.y) * delta * 2;

    // Scale pulse when speaking (driven by amplitude)
    const speakScale = 1.0 + amplitude * 0.05;
    meshRef.current.scale.setScalar(
      THREE.MathUtils.lerp(meshRef.current.scale.x, speakScale, delta * 8)
    );

    // Color transition based on emotion
    if (materialRef.current) {
      const targetColor = new THREE.Color(EMOTION_COLORS[emotion] || EMOTION_COLORS.neutral);
      materialRef.current.color.lerp(targetColor, delta * 3);
      materialRef.current.emissive.lerp(
        targetColor.clone().multiplyScalar(0.15),
        delta * 3
      );
    }
  });

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.3} />
      <directionalLight position={[2, 3, 5]} intensity={0.8} color="#ffffff" />
      <pointLight position={[-3, 1, 2]} intensity={0.4} color="#cc3333" />
      <Environment preset="night" />

      {/* Avatar placeholder — sphere head */}
      <mesh ref={meshRef} position={[0, 0, 0]}>
        <sphereGeometry args={[0.8, 64, 64]} />
        <meshStandardMaterial
          ref={materialRef}
          color="#cc3333"
          roughness={0.6}
          metalness={0.2}
          emissive="#1a0505"
          emissiveIntensity={0.3}
        />
      </mesh>

      {/* Eye indicators (thinking/alert state) */}
      <mesh position={[-0.25, 0.15, 0.7]}>
        <sphereGeometry args={[0.08, 32, 32]} />
        <meshStandardMaterial color="#ffffff" emissive="#ffffff" emissiveIntensity={0.5} />
      </mesh>
      <mesh position={[0.25, 0.15, 0.7]}>
        <sphereGeometry args={[0.08, 32, 32]} />
        <meshStandardMaterial color="#ffffff" emissive="#ffffff" emissiveIntensity={0.5} />
      </mesh>
    </>
  );
}
