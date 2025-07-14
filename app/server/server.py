from flask import Flask
from flask_socketio import SocketIO
import serial

# --- Create Flask App ---
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

# --- Socket.IO Events ---
@socketio.on('connect')
def on_connect():
    print("🔌 Client connected")

@socketio.on('disconnect')
def on_disconnect():
    print("❌ Client disconnected")

@socketio.on('move')
def handle_move():
    print("✅ Received 'move' event")
    ser.write(b"MOVE\n")

# --- Main Entry Point ---
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)
