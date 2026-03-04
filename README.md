# Botanical

Automated plant care system using a gantry-mounted camera and watering pump, controlled via a web dashboard. A Raspberry Pi runs the backend server and serves the React frontend, communicating over serial with an ESP32 that drives stepper motors and a pump. Computer vision (YOLOv8 + OpenCV) detects plants and triggers watering routines automatically.

## Architecture

| Component | Description |
|---|---|
| **Frontend** | React/TypeScript SPA — live camera feed, manual jog controls, scan-and-water trigger |
| **Backend** | Python WebSocket server (`server.py`) — serves the built frontend, streams JPEG video, relays gantry commands over serial |
| **Firmware** | Arduino/ESP32 (`gantry_system.ino`) — stepper motor control, homing, pump actuation via serial commands |
| **CV** | YOLOv8 plant detection + OpenCV processing (`cv_work/`) — identifies plant locations for autonomous watering |

## Prerequisites

- Raspberry Pi (tested on Pi 4/5) with Python 3.10+, Node.js 18+, and `npm`
- ESP32 flashed with `firmware/sketch_jul7a/gantry_system/gantry_system.ino`
- USB serial connection between Pi and ESP32 (`/dev/ttyUSB0` at 115200 baud)
- Cloudflare Tunnel configured (`gantry` tunnel) for remote HTTPS access

## Runbook — Deploying on the Raspberry Pi

### 1. SSH into the Pi

```
ssh aayushkapoor@10.40.227.209
```

### 2. Start the Cloudflare Tunnel (Terminal 1)

This exposes the local server over HTTPS at `https://pi.botanical.live/`.

```
cloudflared tunnel run gantry
```

Leave this terminal running.

### 3. Build and start the server (Terminal 2)

```bash
cd ~/botanical
source .venv/bin/activate
cd ~/botanical/app/frontend && npm install && npm run build
cd ~/botanical
python app/server/server.py
```

The server starts on port 8000, serving the React build and the WebSocket API.

### 4. Access the dashboard

Open **https://pi.botanical.live/** in a browser.

## Project Structure

```
botanical/
├── app/
│   ├── frontend/        # React/TypeScript UI
│   ├── server/
│   │   ├── server.py    # WebSocket server + static file serving
│   │   └── comms.py     # MQTT bridge for ESP32 WiFi comms
│   ├── client/
│   │   └── client.py    # Python WebSocket test client
│   └── requirements.txt
├── cv_work/
│   ├── scan_water.py    # Scan-and-water CV pipeline
│   ├── opencv_detection.py
│   └── plant_cv_demo.py
├── firmware/
│   └── sketch_jul7a/gantry_system/
│       └── gantry_system.ino  # ESP32 stepper + pump firmware
├── video/
│   └── client.py        # Video stream test client
├── run.sh               # Helper launch script
└── README.md
```
