import React, { useEffect, useRef, useState } from "react";

function App() {
  const controlSocketRef = useRef<WebSocket | null>(null);
  const videoSocketRef = useRef<WebSocket | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [videoBlobUrl, setVideoBlobUrl] = useState<string | null>(null);

  useEffect(() => {
    // Connect to control WebSocket
    const controlSocket = new WebSocket("ws://raspberrypi.local:8000/control");
    controlSocket.onopen = () => console.log("✅ Control WebSocket connected");
    controlSocket.onerror = (err) => console.error("❌ Control error:", err);
    controlSocket.onmessage = (e) => console.log("📥 Server:", e.data);
    controlSocket.onclose = () => console.warn("⚠️ Control WebSocket closed");
    controlSocketRef.current = controlSocket;

    // Connect to video WebSocket
    const videoSocket = new WebSocket("ws://raspberrypi.local:8000/video");
    videoSocket.binaryType = "arraybuffer";

    videoSocket.onopen = () => console.log("🎥 Video WebSocket connected");

    videoSocket.onmessage = (event) => {
      const blob = new Blob([event.data], { type: "image/jpeg" });
      const url = URL.createObjectURL(blob);
      setVideoBlobUrl(url);

      // Revoke old blob URL to prevent memory leaks
      if (imgRef.current?.src) {
        URL.revokeObjectURL(imgRef.current.src);
      }
    };

    videoSocket.onerror = (err) => console.error("❌ Video error:", err);
    videoSocket.onclose = () => console.warn("⚠️ Video WebSocket closed");
    videoSocketRef.current = videoSocket;

    // Cleanup on unmount
    return () => {
      controlSocket.close();
      videoSocket.close();
    };
  }, []);

  const sendMoveCommand = () => {
    if (controlSocketRef.current?.readyState === WebSocket.OPEN) {
      controlSocketRef.current.send("MOVE");
      console.log("📤 Sent: MOVE");
    } else {
      console.warn("⚠️ Control socket not open");
    }
  };

  return (
    <div style={{ textAlign: "center", marginTop: "40px" }}>
      <h1>🌿 Plant Bot Control Panel</h1>

      <img
        ref={imgRef}
        src={videoBlobUrl || ""}
        alt="Live Stream"
        width={640}
        height={480}
        style={{
          border: "2px solid black",
          marginBottom: "20px",
          backgroundColor: "#eee",
        }}
      />

      <div>
        <button onClick={sendMoveCommand} style={{ padding: "10px 20px", fontSize: "16px" }}>
          Send MOVE
        </button>
      </div>
    </div>
  );
}

export default App;
