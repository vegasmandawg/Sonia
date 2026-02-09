import React from "react";
import { Canvas } from "@react-three/fiber";
import AvatarScene from "./three/AvatarScene";
import ControlBar from "./components/ControlBar";
import StatusIndicator from "./components/StatusIndicator";
import { useSoniaStore } from "./state/store";

export default function App() {
  const connectionStatus = useSoniaStore((s) => s.connectionStatus);
  const emotion = useSoniaStore((s) => s.emotion);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {/* 3D Avatar */}
      <Canvas
        style={{ width: "100%", height: "100%" }}
        camera={{ position: [0, 0, 3], fov: 35 }}
        gl={{ antialias: true, alpha: true }}
      >
        <AvatarScene />
      </Canvas>

      {/* Status overlay */}
      <StatusIndicator
        connectionStatus={connectionStatus}
        emotion={emotion}
      />

      {/* Bottom control bar */}
      <ControlBar />
    </div>
  );
}
