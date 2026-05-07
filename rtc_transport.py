import asyncio
import logging

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.sdp import candidate_from_sdp

from audio_tracks import AudioReceiver

logger = logging.getLogger(__name__)

class RTCTransport:
    def __init__(self):
        self.pc = RTCPeerConnection()
        self.audio_receivers = []
        self._setup_events()

    def _setup_events(self):
        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"PeerConnection state is {self.pc.connectionState}")
            if self.pc.connectionState == "failed":
                await self.pc.close()

        @self.pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            logger.info(f"ICE Connection state is {self.pc.iceConnectionState}")

        @self.pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            logger.info(f"ICE Gathering state is {self.pc.iceGatheringState}")

        @self.pc.on("track")
        def on_track(track):
            logger.info(f"Received remote track: {track.kind} (id: {track.id})")
            if track.kind == "audio":
                receiver = AudioReceiver(track)
                receiver.start()
                self.audio_receivers.append(receiver)

                @track.on("ended")
                async def on_ended():
                    logger.info(f"Remote track {track.id} ended")
                    await receiver.stop()
                    if receiver in self.audio_receivers:
                        self.audio_receivers.remove(receiver)

    def add_track(self, track):
        """Add a local MediaStreamTrack to the PeerConnection."""
        logger.info(f"Adding local track: {track.kind}")
        self.pc.addTrack(track)

    async def create_offer(self) -> dict:
        """
        Create an SDP offer to send to Janus.
        """
        logger.info("Creating SDP offer...")
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        
        # Wait a brief moment to allow ICE gathering to collect host candidates.
        # aiortc doesn't have an onicecandidate event, so we just give it a little time
        # or we wait until gathering is complete.
        # For simplicity and speed, waiting a fraction of a second is usually enough
        # for local host candidates, but waiting for 'complete' is safer for STUN/TURN.
        # Here we will wait for gathering to complete or timeout.
        try:
            await asyncio.wait_for(self._wait_for_ice_gathering_complete(), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for ICE gathering to complete. Proceeding with gathered candidates.")

        return {
            "type": self.pc.localDescription.type,
            "sdp": self.pc.localDescription.sdp
        }

    async def _wait_for_ice_gathering_complete(self):
        if self.pc.iceGatheringState == "complete":
            return
        
        # Poll the state since there's no awaitable event for this specifically
        # though the event listener fires, we just poll here for simplicity
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

    async def set_remote_answer(self, sdp: str, type: str = "answer"):
        """
        Set the remote description from Janus.
        """
        logger.info("Setting remote description (answer)...")
        answer = RTCSessionDescription(sdp=sdp, type=type)
        await self.pc.setRemoteDescription(answer)

    async def add_ice_candidate(self, candidate_info: dict):
        """
        Add a trickle ICE candidate received from Janus.
        """
        if candidate_info.get("completed"):
            logger.info("Remote ICE gathering completed.")
            return

        sdp_mid = candidate_info.get("sdpMid")
        sdp_mline_index = candidate_info.get("sdpMLineIndex")
        candidate_sdp = candidate_info.get("candidate")

        if candidate_sdp:
            try:
                # Parse candidate from string
                # candidate string looks like "candidate:1 1 UDP 2013266431 192.168.1.1 50000 typ host"
                candidate = candidate_from_sdp(candidate_sdp)
                candidate.sdpMid = sdp_mid
                candidate.sdpMLineIndex = sdp_mline_index
                await self.pc.addIceCandidate(candidate)
                logger.debug(f"Added remote ICE candidate: {candidate_sdp}")
            except Exception as e:
                logger.error(f"Failed to add remote ICE candidate: {e}")

    async def close(self):
        """
        Close the PeerConnection and stop all tracks/receivers.
        """
        logger.info("Closing RTCTransport...")
        for receiver in self.audio_receivers:
            await receiver.stop()
        self.audio_receivers.clear()
        
        await self.pc.close()
        logger.info("RTCTransport closed.")
