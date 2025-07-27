import React, { useEffect, useRef, useState } from "react";
import "./App.css";

const MESSAGE_INTERVAL_MS = 100;

function App() {
  const socketRef = useRef<WebSocket | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sendTimerRef = useRef<number | null>(null);
  const [status, setStatus] = useState("Connecting…");

  /* --- WebSocket setup --------------------------------------------------- */
  useEffect(() => {
    const socket = new WebSocket("ws://raspberrypi.local:8000");
    socket.binaryType = "arraybuffer";

    socket.onopen = () => setStatus("Connected");
    socket.onerror = () => setStatus("Error – see console");
    socket.onclose = () => setStatus("Disconnected");

    socket.onmessage = async (event) => {
      if (typeof event.data === "string") {
        setStatus(event.data);
        return;
      }
      try {
        const blob = new Blob([event.data], { type: "image/jpeg" });
        const bitmap = await createImageBitmap(blob);
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext("2d");
        if (canvas && ctx) {
          ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        }
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
    sock.send(cmd);
    sendTimerRef.current = window.setInterval(
      () => sock.send(cmd),
      MESSAGE_INTERVAL_MS
    );
  };

  const stopSending = () => {
    if (sendTimerRef.current !== null) {
      clearInterval(sendTimerRef.current);
      sendTimerRef.current = null;
    }
  };

  /* --- UI helper -------------------------------------------------------- */
  const holdProps = (cmd: string) => ({
    onMouseDown: () => startSending(cmd),
    onMouseUp: stopSending,
    onMouseLeave: stopSending,
    onTouchStart: (e: React.TouchEvent) => {
      e.preventDefault();
      startSending(cmd);
    },
    onTouchEnd: stopSending,
  });

  return (
    <div className="App">
      <header className="App-header">
        <h1>Plant Control Demo</h1>
        <p className="status">{status}</p>

        <canvas
          ref={canvasRef}
          width={640}
          height={480}
        />

        <div className="controls-diamond">
          <button className="control-button up"    {...holdProps("UP")}>Up</button>
          <button className="control-button left"  {...holdProps("LEFT")}>Left</button>
          <button className="control-button right" {...holdProps("RIGHT")}>Right</button>
          <button className="control-button down"  {...holdProps("DOWN")}>Down</button>
        </div>
      </header>
    </div>
  );
}

export default App;
