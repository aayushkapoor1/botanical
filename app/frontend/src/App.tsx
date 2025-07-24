import React, { useEffect, useRef, useState } from "react";

function App() {
  const socketRef = useRef<WebSocket | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [status, setStatus] = useState<string>("⏳ Connecting…");

  useEffect(() => {
    const socket = new WebSocket("ws://raspberrypi.local:8000");

    /* ↓ tell the browser we want raw bytes, not strings */
    socket.binaryType = "arraybuffer";

    socket.onopen = () => {
      setStatus("✅ Connected");
      console.log("✅ Connected to WebSocket server");
    };

    socket.onmessage = async (event) => {
      /* Text → command reply;  Binary → JPEG frame  */
      if (typeof event.data === "string") {
        console.log("📩 Text from server:", event.data);
        setStatus(event.data);                         // show latest reply
        return;
      }

      // --- Binary JPEG frame ---
      try {
        const blob = new Blob([event.data], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob); // HW‑decoded frame

        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();                               // free GPU memory
      } catch (err) {
        console.error("❌ Frame decode error:", err);
      }
    };

    socket.onerror = (err) => {
      console.error("❌ WebSocket error:", err);
      setStatus("❌ Error – see console");
    };

    socket.onclose = () => {
      console.log("❌ WebSocket closed");
      setStatus("🔌 Disconnected");
    };

    socketRef.current = socket;
    return () => socket.close();
  }, []);

  const sendMove = () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      console.log("📤 Sending MOVE…");
      socketRef.current.send("MOVE");
    } else {
      console.warn("⚠️ WebSocket not open yet.");
    }
  };

  return (
    <div style={{ textAlign: "center", marginTop: 32 }}>
      <h1>React × WebSocket Video Demo</h1>

      {/* live status / command replies */}
      <p>{status}</p>

      <canvas
        ref={canvasRef}
        width={640}
        height={480}
        style={{
          border: "2px solid #444",
          borderRadius: 8,
          background: "#000",
        }}
      />

      <div style={{ marginTop: 16 }}>
        <button onClick={sendMove} style={{ fontSize: 18, padding: "6px 18px" }}>
          Send MOVE
        </button>
      </div>
    </div>
  );
}

export default App;
