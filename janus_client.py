import asyncio
import json
import logging
import random
import string

import websockets

import config
from rtc_transport import RTCTransport

logger = logging.getLogger(__name__)

def generate_transaction_id(length=12):
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(length))

class JanusClient:
    def __init__(self, rtc_transport: RTCTransport):
        self.ws = None
        self.session_id = None
        self.handle_id = None
        self.rtc_transport = rtc_transport
        
        self.transactions = {}
        self.keepalive_task = None
        self.receive_task = None
        self.running = False

    async def connect(self):
        """Connect to Janus WebSocket and start receive loop."""
        logger.info(f"Connecting to Janus at {config.JANUS_WS_URL}...")
        self.ws = await websockets.connect(config.JANUS_WS_URL, subprotocols=["janus-protocol"])
        self.running = True
        
        # Start receive loop
        self.receive_task = asyncio.create_task(self._receive_loop())
        logger.info("Connected to Janus WebSocket.")

    async def close(self):
        """Clean up resources and close connection."""
        self.running = False
        if self.keepalive_task:
            self.keepalive_task.cancel()
        if self.receive_task:
            self.receive_task.cancel()
        if self.ws:
            await self.ws.close()
            logger.info("Janus WebSocket closed.")

    async def _send_request(self, payload: dict) -> dict:
        """Send a request and wait for the response based on transaction ID."""
        transaction_id = generate_transaction_id()
        payload["transaction"] = transaction_id
        
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.handle_id and "handle_id" not in payload:
            payload["handle_id"] = self.handle_id

        future = asyncio.get_event_loop().create_future()
        self.transactions[transaction_id] = future
        
        message = json.dumps(payload)
        logger.debug(f"Sending to Janus: {message}")
        await self.ws.send(message)
        
        try:
            # Wait for response with a timeout
            response = await asyncio.wait_for(future, timeout=10.0)
            return response
        except asyncio.TimeoutError:
            logger.error(f"Timeout waiting for transaction {transaction_id}")
            self.transactions.pop(transaction_id, None)
            raise

    async def _receive_loop(self):
        """Handle incoming messages from Janus."""
        try:
            async for message in self.ws:
                msg = json.loads(message)
                logger.debug(f"Received from Janus: {message}")
                
                janus_type = msg.get("janus")
                transaction = msg.get("transaction")

                # Resolve pending transactions
                if transaction in self.transactions:
                    self.transactions[transaction].set_result(msg)
                    del self.transactions[transaction]
                    continue

                # Handle asynchronous events
                if janus_type == "event":
                    await self._handle_event(msg)
                elif janus_type == "trickle":
                    candidate = msg.get("candidate")
                    if candidate:
                        await self.rtc_transport.add_ice_candidate(candidate)
                elif janus_type == "webrtcup":
                    logger.info("Janus reports WebRTC connection is UP.")
                elif janus_type == "media":
                    kind = msg.get("type")
                    receiving = msg.get("receiving")
                    logger.info(f"Janus media state: {kind} receiving={receiving}")
                elif janus_type == "hangup":
                    reason = msg.get("reason", "Unknown")
                    logger.warning(f"Janus hangup event: {reason}")
                else:
                    logger.debug(f"Unhandled Janus message type: {janus_type}")

        except websockets.ConnectionClosed:
            logger.warning("Janus WebSocket connection closed.")
        except asyncio.CancelledError:
            logger.debug("Receive loop cancelled.")
        except Exception as e:
            logger.error(f"Error in receive loop: {e}")

    async def _handle_event(self, msg: dict):
        """Handle plugin events and JSEP from Janus."""
        plugindata = msg.get("plugindata", {})
        data = plugindata.get("data", {})
        
        event_type = data.get("audiobridge")
        if event_type == "joined":
            logger.info(f"Successfully joined AudioBridge room {data.get('room')} as participant {data.get('id')}")
        elif event_type == "event":
            # Other participants joining/leaving etc.
            pass
            
        jsep = msg.get("jsep")
        if jsep:
            if jsep.get("type") == "answer":
                logger.info("Received SDP answer from Janus.")
                await self.rtc_transport.set_remote_answer(jsep.get("sdp"))
            elif jsep.get("type") == "offer":
                # AudioBridge typically expects an offer from us, but can send offers.
                logger.info("Received SDP offer from Janus (unexpected in this flow).")

    async def _keepalive_loop(self):
        """Send keepalive messages periodically."""
        try:
            while self.running:
                await asyncio.sleep(config.KEEPALIVE_INTERVAL)
                payload = {
                    "janus": "keepalive",
                    "session_id": self.session_id,
                    "transaction": generate_transaction_id()
                }
                await self.ws.send(json.dumps(payload))
                logger.debug("Sent keepalive.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keepalive loop error: {e}")

    async def create_session(self):
        """Create a Janus session."""
        response = await self._send_request({"janus": "create"})
        if response.get("janus") == "success":
            self.session_id = response["data"]["id"]
            logger.info(f"Created Janus session: {self.session_id}")
            self.keepalive_task = asyncio.create_task(self._keepalive_loop())
        else:
            raise Exception(f"Failed to create session: {response}")

    async def attach_plugin(self):
        """Attach to the AudioBridge plugin."""
        response = await self._send_request({
            "janus": "attach",
            "plugin": "janus.plugin.audiobridge"
        })
        if response.get("janus") == "success":
            self.handle_id = response["data"]["id"]
            logger.info(f"Attached to AudioBridge plugin, handle_id: {self.handle_id}")
        else:
            raise Exception(f"Failed to attach plugin: {response}")

    async def join_room(self):
        """Join the configured AudioBridge room."""
        payload = {
            "janus": "message",
            "body": {
                "request": "join",
                "room": config.ROOM_ID,
                "pin": config.ROOM_PIN,
                "display": config.DISPLAY_NAME,
                "group": "default"
            }
        }
        response = await self._send_request(payload)
        plugindata = response.get("plugindata", {}).get("data", {})
        if plugindata.get("audiobridge") != "joined":
            logger.warning(f"Join response did not indicate 'joined': {response}")

    async def configure_webrtc(self):
        """Send SDP offer to Janus to configure WebRTC media."""
        # Create offer from RTCPeerConnection
        offer_jsep = await self.rtc_transport.create_offer()
        
        payload = {
            "janus": "message",
            "body": {
                "request": "configure",
                "muted": False
            },
            "jsep": offer_jsep
        }
        
        response = await self._send_request(payload)
        logger.info("Sent configure request with SDP offer.")
        # Janus will send the SDP answer asynchronously in an 'event' message,
        # which is handled by _handle_event().
