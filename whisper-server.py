#!/usr/bin/env python3
"""
whisper-server.py — Remote Whisper HTTP transcription server
Part of whisper_from_sssDeMoNsss project
Author: sssDeMoNsss | vk.com/basset2

Runs on the HA server (or any Linux machine with GPU).
whisper-ptt.py on Windows PC sends audio here for transcription.

Usage:
    python3 whisper-server.py
    python3 whisper-server.py --model large-v3 --device cuda --port 9000

API:
    POST /transcribe   — upload WAV bytes, returns JSON {text, language, duration_sec}
    GET  /health       — returns server status, model info, GPU info
    GET  /models       — list available faster-whisper models
"""

import argparse
import io
import json
import logging
import os
import sys
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('whisper-server')

# ── Try importing faster-whisper ──────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER = True
except ImportError:
    FASTER_WHISPER = False
    log.warning("faster-whisper not found, trying openai-whisper fallback...")

# ── Try importing openai-whisper as fallback ──────────────────────────────────
if not FASTER_WHISPER:
    try:
        import whisper as openai_whisper
        OPENAI_WHISPER = True
    except ImportError:
        OPENAI_WHISPER = False
        log.error("Neither faster-whisper nor openai-whisper found!")
        log.error("Install: pip install faster-whisper")
        log.error("     or: pip install openai-whisper")
        sys.exit(1)
else:
    OPENAI_WHISPER = False

# ── Global model instance (loaded once, reused) ───────────────────────────────
_model = None
_model_lock = threading.Lock()
_model_name = "large-v3"
_device = "auto"
_compute_type = "float16"
_language = "ru"
_server_start_time = time.time()


def get_gpu_info() -> dict:
    """Get GPU information if available."""
    info = {"available": False, "name": "none", "vram_gb": 0, "cuda_version": "none"}
    try:
        import torch
        if torch.cuda.is_available():
            info["available"] = True
            info["name"] = torch.cuda.get_device_name(0)
            info["vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1024**3, 1
            )
            info["cuda_version"] = torch.version.cuda or "unknown"
    except ImportError:
        pass
    return info


def resolve_device(requested: str) -> tuple[str, str]:
    """
    Resolve device and compute_type.
    Returns (device, compute_type) tuple.
    """
    if requested == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda", "float16"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps", "float16"
        except ImportError:
            pass
        return "cpu", "int8"

    if requested == "cuda":
        try:
            import torch
            if not torch.cuda.is_available():
                log.warning("CUDA requested but not available — falling back to CPU")
                return "cpu", "int8"
        except ImportError:
            log.warning("torch not found — falling back to CPU")
            return "cpu", "int8"
        return "cuda", "float16"

    if requested == "cpu":
        return "cpu", "int8"

    return requested, "float16"


def load_model(model_name: str, device: str, compute_type: str):
    """Load the Whisper model with automatic CPU fallback.

    If CUDA libs (cublas64_12.dll, cudnn_ops_infer64_8.dll, etc.) are missing,
    faster-whisper raises RuntimeError at inference time — NOT at load time.
    We detect this and reload the model on CPU so the server stays functional.
    """
    global _model, _device, _compute_type

    log.info(f"Loading model: {model_name} on {device} ({compute_type})")
    start = time.time()

    def _do_load(dev: str, ct: str):
        if FASTER_WHISPER:
            return WhisperModel(
                model_name,
                device=dev,
                compute_type=ct,
                download_root=str(Path.home() / ".cache" / "whisper-server")
            )
        else:
            return openai_whisper.load_model(model_name, device=dev)

    try:
        _model = _do_load(device, compute_type)
        log.info(f"Model loaded in {time.time()-start:.1f}s ({device}/{compute_type})")
    except Exception as e:
        err = str(e)
        # CUDA library missing → fall back to CPU automatically
        cuda_missing = any(lib in err for lib in (
            "cublas64_", "cudnn", "cufft64_", "curand64_",
            "cannot be loaded", "not found"
        ))
        if cuda_missing and device != "cpu":
            log.warning(
                f"CUDA library missing ({e}). "
                f"Falling back to CPU with int8 quantization. "
                f"To fix: install CUDA Toolkit 12 from https://developer.nvidia.com/cuda-downloads"
            )
            try:
                _model = _do_load("cpu", "int8")
                _device = "cpu"
                _compute_type = "int8"
                log.info(f"CPU fallback model loaded in {time.time()-start:.1f}s")
            except Exception as e2:
                log.error(f"CPU fallback also failed: {e2}")
                raise
        else:
            raise


def transcribe_audio(audio_bytes: bytes, language: Optional[str] = None) -> dict:
    """
    Transcribe audio bytes (WAV/MP3/etc).
    Returns dict: {text, language, duration_sec, processing_sec}
    """
    global _model

    if _model is None:
        raise RuntimeError("Model not loaded")

    lang = language or _language
    start = time.time()

    # Write to temp file (faster-whisper needs file path or numpy array)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        if FASTER_WHISPER:
            segments, info = _model.transcribe(
                tmp_path,
                language=lang if lang != "auto" else None,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=800),
                beam_size=5,
                best_of=5,
                temperature=0.0,
            )
            # Materialise the lazy generator — cublas errors surface here
            try:
                text = " ".join(seg.text.strip() for seg in segments).strip()
            except RuntimeError as gen_err:
                cuda_missing = any(lib in str(gen_err) for lib in (
                    "cublas64_", "cudnn", "cufft64_", "cannot be loaded", "not found"
                ))
                if cuda_missing and _device != "cpu":
                    log.warning(
                        f"CUDA library missing during transcription: {gen_err}. "
                        f"Reloading model on CPU..."
                    )
                    load_model(_model_name, "cpu", "int8")
                    # Retry on CPU
                    segments2, info = _model.transcribe(
                        tmp_path,
                        language=lang if lang != "auto" else None,
                        vad_filter=True,
                        vad_parameters=dict(min_silence_duration_ms=800),
                        beam_size=5,
                        best_of=5,
                        temperature=0.0,
                    )
                    text = " ".join(seg.text.strip() for seg in segments2).strip()
                else:
                    raise
            detected_lang = info.language
            audio_duration = info.duration

        else:
            # openai-whisper fallback
            result = openai_whisper.transcribe(
                _model,
                tmp_path,
                language=lang if lang != "auto" else None,
                verbose=False,
            )
            text = result["text"].strip()
            detected_lang = result.get("language", lang)
            audio_duration = result.get("duration", 0)

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    processing_time = time.time() - start

    # Auto-capitalize first letter
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    return {
        "text": text,
        "language": detected_lang,
        "duration_sec": round(audio_duration, 2),
        "processing_sec": round(processing_time, 2),
        "model": _model_name,
        "device": _device,
    }


# ── HTTP Request Handler ───────────────────────────────────────────────────────
class WhisperHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        """Override to use our logger."""
        log.info(f"{self.client_address[0]} — {format % args}")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 500):
        self.send_json({"error": message}, status)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Language")
        self.end_headers()

    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            uptime = int(time.time() - _server_start_time)
            gpu = get_gpu_info()
            self.send_json({
                "status": "ok",
                "model": _model_name,
                "device": _device,
                "compute_type": _compute_type,
                "language": _language,
                "backend": "faster-whisper" if FASTER_WHISPER else "openai-whisper",
                "uptime_sec": uptime,
                "gpu": gpu,
                "model_loaded": _model is not None,
            })

        elif self.path == "/models":
            models = [
                {"name": "tiny",     "vram_gb": 0.5, "quality": "basic"},
                {"name": "base",     "vram_gb": 0.7, "quality": "good"},
                {"name": "small",    "vram_gb": 1.3, "quality": "great"},
                {"name": "medium",   "vram_gb": 3.0, "quality": "high"},
                {"name": "large-v2", "vram_gb": 5.5, "quality": "maximum"},
                {"name": "large-v3", "vram_gb": 6.0, "quality": "maximum+"},
            ]
            self.send_json({"models": models, "current": _model_name})

        elif self.path == "/shutdown":
            # Graceful shutdown endpoint — called by WebUI Apply & Restart.
            # NSSM will restart the process automatically after it exits.
            # Next launch will read gpu-config.json for model/device settings.
            next_cfg = {}
            try:
                import json as _j
                _cfg_path = Path("C:/whisper-server/gpu-config.json")
                if _cfg_path.exists():
                    next_cfg = _j.loads(_cfg_path.read_text(encoding="utf-8"))
            except Exception:
                pass
            next_model = next_cfg.get("model", "?")
            self.send_json({"ok": True, "message": f"Shutting down to reload with model [{next_model}]"})
            log.info(f"Shutdown requested — next restart will load model [{next_model}]")
            def _do_exit():
                time.sleep(1.0)  # allow HTTP response to fully flush before exit
                import os
                os._exit(0)
            threading.Thread(target=_do_exit, daemon=True).start()

        else:
            self.send_error_json("Not found", 404)

    def do_POST(self):
        if self.path not in ("/transcribe", "/transcribe/"):
            self.send_error_json("Not found", 404)
            return

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_error_json("No audio data provided", 400)
            return

        if content_length > 50 * 1024 * 1024:  # 50 MB max
            self.send_error_json("Audio file too large (max 50 MB)", 413)
            return

        audio_bytes = self.rfile.read(content_length)

        # Optional language override via header
        language = self.headers.get("X-Language") or _language

        if _model is None:
            self.send_error_json("Model not loaded yet, please retry", 503)
            return

        with _model_lock:
            try:
                result = transcribe_audio(audio_bytes, language=language)
                log.info(
                    f"Transcribed {result['duration_sec']:.1f}s audio in "
                    f"{result['processing_sec']:.1f}s: "
                    f"\"{result['text'][:60]}{'...' if len(result['text'])>60 else ''}\""
                )
                self.send_json(result)

            except Exception as e:
                log.error(f"Transcription error: {e}", exc_info=True)
                self.send_error_json(f"Transcription failed: {str(e)}", 500)


# ── Entry point ───────────────────────────────────────────────────────────────
def _read_gpu_config() -> dict:
    """Read gpu-config.json written by WebUI Apply & Restart.
    Returns {} if file does not exist or cannot be parsed.
    """
    candidates = [
        Path("C:/whisper-server/gpu-config.json"),
        Path(__file__).parent / "gpu-config.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def main():
    # ── Read gpu-config.json first — provides defaults for argparse ──────────
    # WebUI writes this file when user clicks "Apply & Restart".
    # Command-line args override it if explicitly provided.
    gpu_cfg = _read_gpu_config()
    cfg_model   = gpu_cfg.get("model",   "large-v2")
    cfg_device  = gpu_cfg.get("device",  "auto")
    cfg_port    = int(gpu_cfg.get("port", 9200))
    cfg_lang    = gpu_cfg.get("language", "ru")
    cfg_compute = gpu_cfg.get("compute_type", "float16")

    parser = argparse.ArgumentParser(
        description="whisper-server — Remote Whisper HTTP transcription server"
    )
    parser.add_argument("--model",    default=cfg_model,
                        help=f"Whisper model name (default from gpu-config: {cfg_model})")
    parser.add_argument("--device",   default=cfg_device,
                        choices=["auto", "cuda", "cpu", "mps"],
                        help=f"Device (default from gpu-config: {cfg_device})")
    parser.add_argument("--language", default=cfg_lang,
                        help=f"Transcription language (default from gpu-config: {cfg_lang})")
    parser.add_argument("--port",     type=int, default=cfg_port,
                        help=f"HTTP port (default from gpu-config: {cfg_port})")
    parser.add_argument("--host",     default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0)")
    args = parser.parse_args()

    global _model_name, _device, _compute_type, _language
    _model_name = args.model
    _language   = args.language

    # Resolve device
    _device, _compute_type = resolve_device(args.device)

    # Override compute_type from gpu-config ONLY if safe:
    # - On CUDA: always use float16 (int8 on CUDA causes DLL errors with some
    #   CUDA versions and is NOT needed for small/medium models — float16 fits fine)
    # - On CPU: always int8 (float16 is not supported on CPU)
    if _device == "cuda":
        _compute_type = "float16"   # safest on CUDA regardless of config
    elif _device == "cpu":
        _compute_type = "int8"
    elif cfg_compute and _device == gpu_cfg.get("device", _device):
        _compute_type = cfg_compute  # honour config only for mps/other

    log.info("=" * 58)
    log.info("  whisper-server — whisper_from_sssDeMoNsss")
    log.info(f"  Model   : {_model_name}")
    log.info(f"  Device  : {_device} ({_compute_type})")
    log.info(f"  Language: {_language}")
    log.info(f"  Backend : {'faster-whisper' if FASTER_WHISPER else 'openai-whisper'}")
    log.info("=" * 58)

    # GPU info
    gpu = get_gpu_info()
    if gpu["available"]:
        log.info(f"  GPU: {gpu['name']} — {gpu['vram_gb']} GB VRAM")
        log.info(f"  CUDA: {gpu['cuda_version']}")
    else:
        log.info("  GPU: not available — running on CPU")
    log.info("=" * 58)

    # Load model in background thread so server starts immediately
    def _load():
        global _model_name
        try:
            load_model(_model_name, _device, _compute_type)
            log.info(f"Model ready. Listening on http://{args.host}:{args.port}")
        except Exception as e:
            log.error(f"Failed to load model: {e}")
            # Try smaller model as fallback
            fallback_chain = ["large-v2", "medium", "small", "base", "tiny"]
            for fb in fallback_chain:
                if fb == _model_name:
                    continue
                log.warning(f"Retrying with model: {fb}")
                try:
                    load_model(fb, _device, _compute_type)
                    _model_name = fb  # keep /health in sync with actual loaded model
                    log.info(f"Fallback model {fb} loaded successfully")
                    break
                except Exception:
                    if _device != "cpu":
                        log.warning(f"GPU failed for {fb}, trying CPU...")
                        try:
                            load_model(fb, "cpu", "int8")
                            _model_name = fb  # keep /health in sync
                            log.info(f"Loaded {fb} on CPU as fallback")
                            break
                        except Exception:
                            continue

    threading.Thread(target=_load, daemon=True).start()

    # Start HTTP server
    server = HTTPServer((args.host, args.port), WhisperHandler)
    log.info(f"HTTP server starting on {args.host}:{args.port}")
    log.info("Endpoints: GET /health   POST /transcribe   GET /models   GET /shutdown")
    log.info("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
