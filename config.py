import os

# Janus Server Configuration
# If running this script on a machine other than the Janus server,
# replace 127.0.0.1 with the server's public IP address or hostname.
JANUS_WS_URL = os.getenv("JANUS_WS_URL", "ws://127.0.0.1:8188")
JANUS_REST_URL = os.getenv("JANUS_REST_URL", "http://127.0.0.1:8088/janus")

# Janus AudioBridge Room Configuration
ROOM_ID = int(os.getenv("ROOM_ID", "7007"))
ROOM_PIN = os.getenv("ROOM_PIN", "7007")

# WebRTC and Audio Configuration
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CODEC = "opus"

# Display name for the WebRTC client in the AudioBridge room
DISPLAY_NAME = "python-webrtc-tester"

# Keepalive interval in seconds
KEEPALIVE_INTERVAL = 30
