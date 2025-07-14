import socketio

sio = socketio.Client()

@sio.event
def connect():
    print("Connected to server")
    sio.emit('move')
    sio.disconnect()

@sio.event
def disconnect():
    print("Disconnected from server")

sio.connect('http://raspberrypi.local:8000')
