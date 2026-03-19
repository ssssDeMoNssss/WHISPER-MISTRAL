#!/usr/bin/env python3
"""
whisper-live-server.py — Real-time streaming WebSocket transcription server
Part of whisper_from_sssDeMoNsss-live project
Author: sssDeMoNsss | vk.com/basset2

Architecture:
  - WebSocket server on port 9201 (default)
  - Client sends raw PCM audio chunks (int16, 16kHz, mono) continuously
  - Server processes chunks with faster-whisper in streaming segments
  - Server sends back intermediate text results as they arrive
  - Client updates display in real-time

Protocol (JSON over WebSocket):
  Client → Server:
    {"type":"start","language":"ru","translate":false}  — begin session
    {"type":"audio","data":<base64 PCM bytes>}           — audio chunk
    {"type":"end"}                                        — stop, get final result

  Server → Client:
    {"type":"partial","text":"...","segment_id":N}        — live update
    {"type":"final","text":"...","translation":"..."}     — session done
    {"type":"ready","model":"medium","device":"cuda"}     — server ready
    {"type":"error","message":"..."}                      — error
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import time
import threading
import numpy as np
from pathlib import Path
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('whisper-live')

# ── Try websockets library ────────────────────────────────────────────────────
try:
    import websockets
    import websockets.server
    WEBSOCKETS_OK = True
except ImportError:
    WEBSOCKETS_OK = False
    log.error("websockets not installed. Run: pip install websockets")

# ── Try faster-whisper ────────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER = True
except ImportError:
    FASTER_WHISPER = False
    log.error("faster-whisper not installed. Run: pip install faster-whisper")

# ── Global state ──────────────────────────────────────────────────────────────
_model:       Optional[object] = None
_model_name:  str = "medium"
_device:      str = "cpu"
_compute_type: str = "int8"
_language:    str = "ru"
_server_start = time.time()
_active_sessions = 0

SAMPLE_RATE  = 16000
CHUNK_SECONDS = 1.5    # seconds of audio per processing chunk
MIN_AUDIO_SEC = 0.3    # don't process clips shorter than this


def load_model(model_name: str, device: str, compute_type: str):
    """Load faster-whisper model. Returns model instance."""
    global _model, _model_name, _device, _compute_type
    log.info(f"Loading model [{model_name}] on {device} ({compute_type})...")
    t0 = time.time()
    _model = WhisperModel(model_name, device=device, compute_type=compute_type)
    _model_name = model_name
    _device = device
    _compute_type = compute_type
    log.info(f"Model loaded in {time.time()-t0:.1f}s")
    return _model


def transcribe_chunk(audio_np: np.ndarray, language: str,
                     translate: bool = False) -> str:
    """Transcribe a numpy audio array. Returns text string."""
    if _model is None:
        return ""
    if len(audio_np) < SAMPLE_RATE * MIN_AUDIO_SEC:
        return ""
    audio_f32 = audio_np.astype(np.float32) / 32768.0
    task = "translate" if translate else "transcribe"
    try:
        segments, _ = _model.transcribe(
            audio_f32,
            language=language,
            task=task,
            beam_size=3,
            best_of=2,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=True,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text
    except Exception as e:
        log.warning(f"Transcription error: {e}")
        return ""


class StreamingSession:
    """Manages one WebSocket client's streaming session."""

    def __init__(self, ws, language: str = "ru", translate: bool = False):
        self.ws        = ws
        self.language  = language
        self.translate = translate

        self._audio_buf  = np.array([], dtype=np.int16)  # accumulated raw PCM
        self._text_parts: list[str] = []                  # confirmed segments
        self._last_sent  = ""                              # last partial sent
        self._running    = True
        self._lock       = threading.Lock()
        self._segment_id = 0

    def add_audio(self, pcm_bytes: bytes):
        """Add raw PCM int16 bytes to buffer."""
        chunk = np.frombuffer(pcm_bytes, dtype=np.int16)
        with self._lock:
            self._audio_buf = np.concatenate([self._audio_buf, chunk])

    def get_audio_copy(self) -> np.ndarray:
        with self._lock:
            return self._audio_buf.copy()

    def stop(self):
        self._running = False

    async def send(self, msg: dict):
        try:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass

    async def run_streaming(self):
        """
        Main streaming loop: every CHUNK_SECONDS, transcribe what we have
        and send a partial update.  Runs until stop() is called.
        """
        INTERVAL = CHUNK_SECONDS
        while self._running:
            await asyncio.sleep(INTERVAL)
            audio = self.get_audio_copy()
            duration = len(audio) / SAMPLE_RATE
            if duration < MIN_AUDIO_SEC:
                continue

            # Transcribe the whole accumulated audio for context accuracy
            t0 = time.time()
            text = transcribe_chunk(audio, self.language, translate=False)
            elapsed = time.time() - t0

            if text and text != self._last_sent:
                self._last_sent = text
                self._segment_id += 1
                log.info(f"Partial [{elapsed:.2f}s | {duration:.1f}s audio]: {text[:60]}")
                await self.send({
                    "type":       "partial",
                    "text":       text,
                    "segment_id": self._segment_id,
                    "proc_sec":   round(elapsed, 2),
                    "audio_sec":  round(duration, 1),
                })

    async def finalize(self) -> dict:
        """
        Final transcription on the full buffer.
        If translate=True, also do translation pass.
        Returns {"text": ru_text, "translation": en_text}.
        """
        audio = self.get_audio_copy()
        duration = len(audio) / SAMPLE_RATE
        if duration < MIN_AUDIO_SEC:
            return {"text": "", "translation": ""}

        log.info(f"Finalizing {duration:.1f}s of audio...")
        t0 = time.time()

        # Full-audio transcription (most accurate — uses complete context)
        ru_text = transcribe_chunk(audio, self.language, translate=False)
        en_text = ""

        if self.translate and ru_text:
            en_text = transcribe_chunk(audio, self.language, translate=True)

        elapsed = time.time() - t0
        log.info(f"Final [{elapsed:.2f}s]: RU={ru_text[:50]} | EN={en_text[:50]}")
        return {"text": ru_text, "translation": en_text, "proc_sec": round(elapsed, 2)}


async def handle_client(websocket):
    """Handle one WebSocket connection."""
    global _active_sessions
    _active_sessions += 1
    addr = str(websocket.remote_address)
    log.info(f"Client connected: {addr} (sessions: {_active_sessions})")

    session: Optional[StreamingSession] = None
    stream_task: Optional[asyncio.Task]  = None

    try:
        # Send ready signal
        if _model is not None:
            await websocket.send(json.dumps({
                "type":   "ready",
                "model":  _model_name,
                "device": _device,
            }))

        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = msg.get("type", "")

            if mtype == "start":
                # Begin new streaming session
                lang      = msg.get("language", _language)
                translate = bool(msg.get("translate", False))
                session   = StreamingSession(websocket, lang, translate)

                # Launch background streaming loop
                stream_task = asyncio.create_task(session.run_streaming())
                log.info(f"Session started: lang={lang} translate={translate}")

            elif mtype == "audio" and session:
                # Receive audio chunk
                data = msg.get("data", "")
                if data:
                    try:
                        pcm = base64.b64decode(data)
                        session.add_audio(pcm)
                    except Exception:
                        pass

            elif mtype == "end" and session:
                # Client finished speaking — finalize
                session.stop()
                if stream_task:
                    stream_task.cancel()
                    try:
                        await stream_task
                    except asyncio.CancelledError:
                        pass

                result = await session.finalize()
                await websocket.send(json.dumps({
                    "type":        "final",
                    "text":        result.get("text", ""),
                    "translation": result.get("translation", ""),
                    "proc_sec":    result.get("proc_sec", 0),
                }))
                session = None
                stream_task = None
                log.info(f"Session ended for {addr}")

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log.error(f"Handler error for {addr}: {e}")
    finally:
        if session:
            session.stop()
        if stream_task and not stream_task.done():
            stream_task.cancel()
        _active_sessions -= 1
        log.info(f"Client disconnected: {addr} (sessions: {_active_sessions})")


async def health_endpoint(reader, writer):
    """Simple TCP health check on port+1 (returns JSON status)."""
    try:
        data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        request = data.decode(errors="replace")
        if "GET" in request:
            body = json.dumps({
                "status":       "ok",
                "model":        _model_name,
                "model_loaded": _model is not None,
                "device":       _device,
                "compute_type": _compute_type,
                "language":     _language,
                "sessions":     _active_sessions,
                "uptime_sec":   int(time.time() - _server_start),
                "backend":      "faster-whisper-streaming",
                "mode":         "live",
            }, ensure_ascii=False)
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
                + body
            )
            writer.write(response.encode())
            await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


def _read_gpu_config() -> dict:
    for p in [Path("C:/whisper-server/gpu-config-live.json"),
              Path("C:/whisper-server/gpu-config.json"),
              Path(__file__).parent / "gpu-config-live.json"]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


async def main_async(args):
    global _language
    _language = args.language

    # Resolve device
    device      = args.device
    comp_type   = "float16" if device == "cuda" else "int8"
    if args.compute_type:
        comp_type = args.compute_type

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        comp_type = "float16" if device == "cuda" else "int8"

    # Load model
    load_model(args.model, device, comp_type)

    ws_port     = args.port
    health_port = args.port + 1

    log.info("=" * 58)
    log.info("  whisper-live-server — whisper_from_sssDeMoNsss-live")
    log.info(f"  Model   : {_model_name}")
    log.info(f"  Device  : {device} ({comp_type})")
    log.info(f"  Language: {_language}")
    log.info(f"  WS port : {ws_port}")
    log.info("=" * 58)
    log.info(f"  WebSocket : ws://0.0.0.0:{ws_port}")
    log.info(f"  Health    : http://0.0.0.0:{health_port}/health")
    log.info("  Press Ctrl+C to stop")
    log.info("=" * 58)

    # Start health HTTP server and WebSocket server, both properly managed
    # so all sockets are closed cleanly on exit (KeyboardInterrupt / asyncio.run cancel)
    stop_event = asyncio.Event()
    async with await asyncio.start_server(health_endpoint, "0.0.0.0", health_port):
        async with websockets.serve(handle_client, "0.0.0.0", ws_port):
            log.info(f"Server ready. Waiting for connections on ws://0.0.0.0:{ws_port}")
            await stop_event.wait()  # run forever


def main():
    if not WEBSOCKETS_OK:
        log.error("Install websockets: pip install websockets")
        sys.exit(1)
    if not FASTER_WHISPER:
        log.error("Install faster-whisper: pip install faster-whisper")
        sys.exit(1)

    cfg = _read_gpu_config()

    parser = argparse.ArgumentParser(
        description="whisper-live-server — streaming WebSocket transcription server"
    )
    parser.add_argument("--model",        default=cfg.get("model", "medium"))
    parser.add_argument("--device",       default=cfg.get("device", "auto"),
                        choices=["auto", "cuda", "cpu"])
    parser.add_argument("--compute-type", default=cfg.get("compute_type", ""),
                        dest="compute_type")
    parser.add_argument("--language",     default=cfg.get("language", "ru"))
    parser.add_argument("--port",         type=int,
                        default=int(cfg.get("port", 9201)))
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
