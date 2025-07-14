from flask import Flask
from flask_socketio import SocketIO
import serial

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)  

@socketio.on('move')
def handle_move():
    ser.write(b"MOVE\n")
    print("Stepper command sent")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000)
