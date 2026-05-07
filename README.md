# Python Janus WebRTC Transport Service

This is a standalone, production-grade Python service that connects to a Janus Gateway (AudioBridge plugin) via WebRTC. It uses `aiortc` for media transport and serves as the baseline realtime media transport layer for a future Pipecat AI voice agent.

## Features
- **Janus Signaling**: WebSocket based protocol to handle `create`, `attach`, and `audiobridge` events.
- **WebRTC Transport**: Headless `aiortc` peer connection with Opus audio negotiation (16kHz mono).
- **Trickle ICE**: Automatic handling of incoming ICE candidates from Janus.
- **Bidirectional Audio**: 
  - Streams a synthetic 440Hz sine wave to validate the outbound RTP path.
  - Receives and logs inbound RTP audio frames to validate duplex capabilities.
- **Production-Ready**: asyncio-based, non-blocking flow, graceful shutdown, structured logging, and keepalives.

## Requirements

- Python 3.11+
- The `ffmpeg` or `libav` libraries (required by `av` for audio processing)
  - Ubuntu/Debian: `sudo apt-get install libavdevice-dev libavfilter-dev libopus-dev`
  - Windows: Should be bundled with the `av` wheel, but ensure you have the appropriate VC++ redistributables.

## Installation

1. Clone or navigate to the project directory:
   ```bash
   cd janus-test
   ```

2. Create a virtual environment and activate it:
   ```bash
   python -m venv venv
   # Linux/macOS
   source venv/bin/activate
   # Windows
   .\venv\Scripts\activate
   ```

3. Install the specific dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Modify `config.py` or set the environment variables to point to your Janus Server:

- `JANUS_WS_URL`: The WebSocket URL for Janus (default: `ws://127.0.0.1:8188`)
- `ROOM_ID`: The AudioBridge room ID to join (default: `7007`)
- `ROOM_PIN`: The PIN for the room (default: `7007`)

> **Note**: If your Janus server is running on a remote EC2 instance, ensure you update `127.0.0.1` to the server's public IP address.

## Running the Service

Start the service via:

```bash
python main.py
```

### Expected Behavior
1. The script will connect to Janus via WebSocket and create a session.
2. It will attach to `janus.plugin.audiobridge` and join Room `7007`.
3. It will generate an SDP Offer and send it to Janus.
4. Janus will reply with an SDP Answer.
5. The ICE connection state will transition to `checking` -> `connected` -> `completed`.
6. The `SineWaveAudioTrack` will begin generating and sending Opus frames.
7. If anyone else speaks in the room (e.g., via a SIP client), the script will log inbound audio frames.

## Troubleshooting

### ICE & WebRTC Issues
- **ICE state stuck at "checking"**: This typically means a firewall (like AWS Security Groups) is blocking the UDP ports used for RTP. Ensure that the ephemeral port range (usually 10000-20000) is open on the EC2 instance for UDP traffic.
- **No SDP Answer**: Ensure the Janus AudioBridge plugin is correctly configured, loaded, and Room 7007 exists.

### aiortc Best Practices
- `aiortc` uses `asyncio` extensively. Never place blocking synchronous code (like heavy compute or blocking network requests) in the track's `recv()` method or in event handlers.
- Audio frames are dispatched via the `av.AudioFrame` object. Timing must be strictly adhered to using `pts` (presentation timestamp) and `time_base`.

## Future Migration Path to Pipecat

This service validates the transport layer. To migrate this into the Pipecat architecture:
1. **Remove the Sine Wave**: Replace `SineWaveAudioTrack` with Pipecat's `FrameSerializer`.
2. **Pipeline Integration**: The incoming audio stream in `rtc_transport.py` should be pushed into a Pipecat async queue (`push_frame`) instead of simply logging it.
3. **Replace FreeSWITCH**: In Pipecat, you can replace the default `FreeSwitchAudioSerializer` with a custom `JanusWebRTCSerializer` that utilizes the signaling logic from `janus_client.py`.
4. **LLM/VAD**: Once the audio flows into Pipecat, standard VAD, STT, and LLM processing will trigger just as if the call came from a standard telephony provider.
