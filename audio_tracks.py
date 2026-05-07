import asyncio
import logging
import math
import time
from fractions import Fraction

import numpy as np
from aiortc import MediaStreamTrack
from av import AudioFrame

logger = logging.getLogger(__name__)

class SineWaveAudioTrack(MediaStreamTrack):
    """
    An audio track that generates a synthetic 440Hz sine wave.
    Used to validate outbound RTP audio flow.
    """
    kind = "audio"

    def __init__(self, sample_rate=16000, frequency=440.0):
        super().__init__()
        self.sample_rate = sample_rate
        self.frequency = frequency
        self.time = 0
        self.samples_per_frame = int(sample_rate * 0.02)  # 20ms frames
        self.channels = 1
        self._timestamp = 0
        self._start_time = None
        logger.info(f"Initialized SineWaveAudioTrack ({self.sample_rate}Hz, {self.frequency}Hz tone)")

    async def recv(self):
        """
        Return the next audio frame.
        """
        # Maintain accurate timing
        if self._start_time is None:
            self._start_time = time.time()
            self._start_time_pts = 0
        else:
            wait = self._start_time + (self._timestamp / self.sample_rate) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        # Generate sine wave
        t = np.arange(self.time, self.time + self.samples_per_frame) / self.sample_rate
        audio_data = np.sin(2 * np.pi * self.frequency * t) * 10000
        audio_data = audio_data.astype(np.int16)

        self.time += self.samples_per_frame

        # Create AV audio frame
        frame = AudioFrame(format="s16", layout="mono", samples=self.samples_per_frame)
        frame.sample_rate = self.sample_rate
        frame.planes[0].update(audio_data.tobytes())

        frame.pts = self._timestamp
        frame.time_base = Fraction(1, self.sample_rate)
        self._timestamp += self.samples_per_frame

        return frame

class AudioReceiver:
    """
    Consumes an incoming aiortc.MediaStreamTrack and logs statistics.
    Used to validate inbound RTP audio reception.
    """
    def __init__(self, track: MediaStreamTrack):
        self.track = track
        self._task = None
        self.frames_received = 0
        self.last_log_time = time.time()
        self.active = False

    def start(self):
        self.active = True
        self._task = asyncio.create_task(self._consume_track())
        logger.info(f"Started AudioReceiver for track {self.track.id}")

    async def stop(self):
        self.active = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"Stopped AudioReceiver. Total frames received: {self.frames_received}")

    async def _consume_track(self):
        try:
            while self.active:
                frame = await self.track.recv()
                self.frames_received += 1
                
                # Log stats every 50 frames (~1 second)
                if self.frames_received % 50 == 0:
                    current_time = time.time()
                    fps = 50 / (current_time - self.last_log_time)
                    self.last_log_time = current_time
                    logger.debug(
                        f"Inbound Audio: received 50 frames (total: {self.frames_received}, "
                        f"format: {frame.format.name}, samples: {frame.samples}, ~{fps:.1f} fps)"
                    )
        except asyncio.CancelledError:
            logger.debug("AudioReceiver consumption task cancelled.")
        except Exception as e:
            logger.error(f"Error in AudioReceiver: {e}")
