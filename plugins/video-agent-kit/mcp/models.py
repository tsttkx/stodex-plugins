"""User-selected Stodex media backends. No third-party host credentials are used."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

from media import AUDIO, VIDEO, config, ff, output, probe, rendered, run, source
from protocol import choice, fields, STRING, tool


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def profile(task):
    file = os.getenv("STODEX_MEDIA_MODELS")
    if not file or not Path(file).exists():
        return {"mode": "local", "model": "small" if task == "transcription" else "", "baseURL": "", "voice": ""}
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    return data[task]


def request(settings, route, *, body=None, mime=None, binary_output=None, timeout=360):
    endpoint = settings.get("baseURL") or "http://127.0.0.1:8188"
    parsed = urlsplit(endpoint)
    local = parsed.hostname in ("127.0.0.1", "::1", "localhost")
    if settings["mode"] == "local" and not local or parsed.username or parsed.password or parsed.query or parsed.fragment or not (
            parsed.scheme == "https" or parsed.scheme == "http" and local):
        raise ValueError("Invalid media service address in Stodex Settings")
    headers = {"User-Agent": "Stodex-Video-Agent-Kit/1.0"}
    if settings["mode"] == "api" and settings.get("apiKey"):
        headers["Authorization"] = "Bearer " + settings["apiKey"]
    if isinstance(body, dict):
        body, mime = json.dumps(body).encode(), "application/json"
    if mime:
        headers["Content-Type"] = mime
    req = Request(endpoint.rstrip("/") + "/" + route.lstrip("/"), data=body, headers=headers)
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            if binary_output:
                with Path(binary_output).open("wb") as dest:
                    shutil.copyfileobj(response, dest, length=1024 * 1024)
                return
            raw = response.read(16_000_001)
            if len(raw) > 16_000_000:
                raise ValueError("Media service response too large")
            return json.loads(raw)
    except HTTPError as e:
        # Providers can echo request data and headers. Never return either to the model.
        raise ValueError(f"Media service returned HTTP {e.code} for /{route.split('?')[0]}. Check the configured model, endpoint and quota.") from None


def multipart(parameters, file=None):
    boundary = "stodex" + uuid.uuid4().hex
    body = bytearray()
    for name, value in parameters.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    if file:
        name, path, mime = file
        if path.stat().st_size > 25_000_000:
            raise ValueError("Audio upload exceeds 25 MB. Transcribe shorter clips.")
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"audio.wav\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), "multipart/form-data; boundary=" + boundary


@tool("Transcribe a file with the speech-to-text model selected in Stodex. Local mode uses faster-whisper or whisper.cpp. Returns text and source timestamps when provided by the recognizer.", fields(
      {"path": STRING, "language": STRING}, ["path"]))
def transcribe(path, language=None):
    media = source(path, VIDEO | AUDIO)
    settings = profile("transcription")
    with tempfile.TemporaryDirectory() as temp:
        wav = Path(temp) / "speech.wav"
        ff(["-i", media, "-map", "0:a:0", "-ac", 1, "-ar", 16000, "-c:a", "pcm_s16le", wav])
        if settings["mode"] == "api":
            model = settings["model"]
            spec = {"model": model, "response_format": "verbose_json" if "whisper" in model.lower() else "json"}
            if language:
                spec["language"] = language
            body, mime = multipart(spec, ("file", wav, "audio/wav"))
            data = request(settings, "/audio/transcriptions", body=body, mime=mime)
            if not isinstance(data.get("text"), str):
                raise ValueError("Provider did not return transcription text")
            return {"text": data["text"], "segments": [{k: row[k] for k in ("start", "end", "text")} for row in data.get("segments", [])]}
        local = config()
        model = settings.get("model") or "small"
        cli = local.get("whisper_cli") or shutil.which("whisper-cli")
        if cli and (Path(model).is_file() or local.get("whisper_models", {}).get(model)):
            weights = source(str(Path(model)) if Path(model).is_file() else local["whisper_models"][model])
            out = Path(temp) / "recognition"
            run([cli, "-m", weights, "-f", wav, "-l", language or "auto", "-oj", "-of", out])
            rows = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["transcription"]
            segments = [{"start": row["offsets"]["from"]/1000, "end": row["offsets"]["to"]/1000, "text": row["text"].strip()} for row in rows]
        else:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ValueError("Install faster-whisper in the plugin's Python or configure whisper_cli and a GGML model. See setup-guide.") from None
            engine = WhisperModel(model, device="cpu", compute_type="int8")
            spans, _ = engine.transcribe(str(wav), language=language, beam_size=3)
            segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in spans]
    return {"text": " ".join(s["text"] for s in segments), "segments": segments}


@tool("Synthesize a WAV narration using the selected Stodex speech model or the local system voice.", fields(
      {"text": STRING, "output_path": STRING, "voice": STRING}, ["text", "output_path"]))
def narrate(text, output_path, voice=None):
    if len(text) > 20000:
        raise ValueError("Split long narration into scenes of at most 20,000 characters.")
    settings = profile("speech")
    voice = voice or settings.get("voice")
    with output(output_path, {".wav"}) as dest:
        if settings["mode"] == "api":
            request(settings, "/audio/speech", body={"model": settings["model"], "input": text, "voice": voice or "alloy", "response_format": "wav"}, binary_output=dest)
        elif os.name == "nt":
            # Text and paths are passed as data. The PowerShell program is constant.
            script = ("$ErrorActionPreference='Stop';$j=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::ReadLine()))|ConvertFrom-Json;"
                      "Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                      "try{if($j.voice){$s.SelectVoice($j.voice)};$s.SetOutputToWaveFile($j.file);$s.Speak($j.text)}finally{$s.Dispose()}")
            import base64
            data = base64.b64encode(json.dumps({"text": text, "file": str(dest), "voice": voice}).encode()) + b"\n"
            run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], data=data)
        elif sys.platform == "darwin":
            run(["say", *(["-v", voice] if voice else []), "-o", dest, "--file-format=WAVE", "--data-format=LEI16@22050", "-f", "-"], data=text.encode())
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise ValueError("Install espeak-ng or configure an audio API in Stodex.")
            run([exe, *(["-v", voice] if voice else []), "-w", dest, "--stdin"], data=text.encode())
        info = probe(dest)
        if not any(s["codec_type"] == "audio" for s in info["streams"]) or info["duration"] <= 0:
            raise ValueError("The selected service did not produce playable speech")
    return rendered(output_path)


@tool("Recover a legacy Video Agent Kit 1.0 video job using its original job and mode. For jobs from Stodex model settings, use call_model with action=video_status and the original model and job.", fields(
      {"job": STRING, "mode": choice("api","local"), "output_path": STRING}, ["job", "mode"]))
def video_result(job, mode, output_path=None):
    if not re.fullmatch(r"[\w-]{1,160}", job):
        raise ValueError("Invalid job ID")
    settings = profile("video")
    if settings["mode"] != mode:
        raise ValueError("Restore the video service that owns this job in Settings")
    if mode == "api":
        data = request(settings, "/videos/" + quote(job))
        status = data.get("status", "unknown")
        link = "/videos/" + quote(job) + "/content"
    else:
        data = request(settings, "/history/" + quote(job)).get(job)
        if not data:
            return {"job": job, "status": "pending"}
        status = "failed" if data.get("status", {}).get("status_str") == "error" else "completed"
        files = [f for node in data.get("outputs", {}).values() for group in ("videos", "gifs", "images")
                 for f in node.get(group, []) if isinstance(f, dict) and Path(f.get("filename", "")).suffix.lower() in VIDEO]
        if status == "completed" and not files:
            raise ValueError("The ComfyUI workflow did not return a video file")
        link = "/view?" + urlencode({k: files[0].get(k, "") for k in ("filename", "subfolder", "type")}) if files else ""
    if status != "completed" or not output_path:
        return {"job": job, "status": status}
    with output(output_path, {".mp4"}) as dest:
        downloaded = dest.parent / "generation.media"
        request(settings, link, binary_output=downloaded)
        ff(["-i", downloaded, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", dest])
    return rendered(output_path) | {"job": job, "status": status}
