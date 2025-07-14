import React, { useEffect, useRef } from 'react';

function App() {
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const socket = new WebSocket("ws://raspberrypi.local:8000");

    socket.onopen = () => {
      console.log("✅ Connected to WebSocket server");
    };

    socket.onerror = (error) => {
      console.error("❌ WebSocket error:", error);
    };

    socket.onmessage = (event) => {
      console.log("📥 Message from server:", event.data);
    };

    socket.onclose = () => {
      console.log("❌ WebSocket closed");
    };

    socketRef.current = socket;

    return () => {
      socket.close();
    };
  }, []);

  const sendMove = () => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      console.log("📤 Sending MOVE...");
      socketRef.current.send("MOVE");
    } else {
      console.warn("⚠️ WebSocket is not open yet.");
    }
  };

  return (
    <div style={{ textAlign: "center", marginTop: "50px" }}>
      <h1>React to WebSocket</h1>
      <button onClick={sendMove}>Send MOVE</button>
    </div>
  );
}

export default App;
