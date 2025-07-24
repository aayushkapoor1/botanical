import React, { useEffect, useRef, useState } from "react";

const MESSAGE_INTERVAL_MS = 100;         // adjust as needed

function App() {
  const socketRef = useRef<WebSocket | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sendTimerRef = useRef<number | null>(null); // keeps interval id
  const [status, setStatus] = useState("Connecting…");

  /* --- WebSocket setup --------------------------------------------------- */
  useEffect(() => {
    const socket = new WebSocket("ws://raspberrypi.local:8000");
    socket.binaryType = "arraybuffer";

    socket.onopen    = () => setStatus("Connected");
    socket.onerror   = () => setStatus("Error – see console");
    socket.onclose   = () => setStatus("Disconnected");

    socket.onmessage = async (event) => {
      if (typeof event.data === "string") {
        setStatus(event.data);               // latest text reply
        return;
      }

      /* JPEG frame */
      try {
        const blob   = new Blob([event.data], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob);

        const canvas = canvasRef.current;
        const ctx    = canvas?.getContext("2d");
        if (canvas && ctx)
          ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

        bitmap.close();
      } catch (err) {
        console.error("Frame decode error:", err);
      }
    };

    socketRef.current = socket;
    return () => socket.close();
  }, []);

  /* --- hold-to-repeat helper -------------------------------------------- */
  const startSending = (cmd: string) => {
    const sock = socketRef.current;
    if (!sock || sock.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket not open yet");
      return;
    }

    // send one immediately …
    sock.send(cmd);

    // … and keep sending while held
    sendTimerRef.current = window.setInterval(() => sock.send(cmd), MESSAGE_INTERVAL_MS);
  };

  const stopSending = () => {
    if (sendTimerRef.current !== null) {
      clearInterval(sendTimerRef.current);
      sendTimerRef.current = null;
    }
  };

  /* --- UI ---------------------------------------------------------------- */
  const btnStyle: React.CSSProperties = {
    fontSize: 18,
    padding: "6px 18px",
    margin: 4,
    width: 100,
  };

  // helper to wire up press + release handlers
  const holdProps = (cmd: string) => ({
    onMouseDown: () => startSending(cmd),
    onMouseUp: stopSending,
    onMouseLeave: stopSending,
    onTouchStart: (e: React.TouchEvent) => {
      e.preventDefault();     // avoid double-fire on mobile
      startSending(cmd);
    },
    onTouchEnd: stopSending,
  });

  return (
    <div style={{ textAlign: "center", marginTop: 32 }}>
      <h1>React × WebSocket Video Demo</h1>
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
        <div>
          <button style={btnStyle} {...holdProps("UP")}>Up</button>
        </div>
        <div>
          <button style={btnStyle} {...holdProps("LEFT")}>Left</button>
          <button style={btnStyle} {...holdProps("DOWN")}>Down</button>
          <button style={btnStyle} {...holdProps("RIGHT")}>Right</button>
        </div>
      </div>
    </div>
  );
}

export default App;
