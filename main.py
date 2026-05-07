import asyncio
import logging
import signal
import sys

from janus_client import JanusClient
from rtc_transport import RTCTransport
from audio_tracks import SineWaveAudioTrack
import config

# Setup structured logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
# Silence verbose loggers
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

logger = logging.getLogger("main")

async def run_client():
    rtc = RTCTransport()
    client = JanusClient(rtc)
    
    # Setup graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def shutdown():
        logger.info("Shutdown signal received...")
        stop_event.set()
        
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown)
    except NotImplementedError:
        # Windows does not support add_signal_handler
        pass

    try:
        # Connect to Janus WebSocket
        await client.connect()
        
        # Create session and attach to AudioBridge
        await client.create_session()
        await client.attach_plugin()
        
        # Add outbound test audio track (440Hz Sine Wave)
        audio_track = SineWaveAudioTrack(
            sample_rate=config.AUDIO_SAMPLE_RATE,
            frequency=440.0
        )
        rtc.add_track(audio_track)
        
        # Join Room 7007
        await client.join_room()
        
        # Configure WebRTC (send SDP offer)
        await client.configure_webrtc()
        
        logger.info("Service is running. Press Ctrl+C to stop.")
        
        # Wait until shutdown signal
        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Fatal error in main loop: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up resources...")
        await client.close()
        await rtc.close()
        logger.info("Cleanup complete. Exiting.")

if __name__ == "__main__":
    logger.info("Starting Janus WebRTC Transport Service...")
    # Windows-specific event loop policy for graceful shutdown with aiortc if needed
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        pass
