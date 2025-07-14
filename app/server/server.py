from flask import Flask
import serial

app = Flask(__name__)
ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)  # Adjust if needed

@app.route('/move', methods=['POST'])
def move_stepper():
    ser.write(b"MOVE\n")
    return "Stepper command sent", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)