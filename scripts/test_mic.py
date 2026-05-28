"""Teste de voz com microfone do PC: gravar -> Whisper STT -> Thina -> altifalante.

Simula o que o Home Assistant faz (STT + POST /v1/conversar), mas reproduz
a resposta nos altifalantes deste PC em vez de depender do ReSpeaker.

Uso:
  pip install -r requirements-mic.txt
  python scripts/test_mic.py
  python scripts/test_mic.py --list-devices
  python scripts/test_mic.py --area-id sala --seconds 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import wave
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from config import get_settings  # noqa: E402
except ModuleNotFoundError as exc:
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    print(
        f"Dependencia em falta ({exc.name}). Use o Python do projeto:\n"
        f"  .\\test-mic.ps1\n"
        f"  ou: {venv_py} scripts\\test_mic.py"
    )
    sys.exit(1)

SAMPLE_RATE = 16_000
CHANNELS = 1


def thina_base_url(settings) -> str:
    return f"http://127.0.0.1:{settings.thina_port}"


def list_input_devices() -> None:
    import sounddevice as sd

    print("Dispositivos de audio (entrada):")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            default = " [PADRAO]" if i == sd.default.device[0] else ""
            print(f"  [{i}] {dev['name']}{default}")


def record_wav(path: Path, seconds: float, device: int | None) -> None:
    import numpy as np
    import sounddevice as sd

    print(f"\nGravando {seconds:.0f}s... fale agora.")
    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(
        frames,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=device,
    )
    sd.wait()
    peak = float(np.max(np.abs(audio)))
    if peak < 0.01:
        print("AVISO: sinal muito baixo — microfone mudo ou dispositivo errado?")

    pcm = (audio.flatten() * 32767).astype("int16")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    print(f"Gravacao salva: {path} ({path.stat().st_size} bytes)")


def transcribe(wav_path: Path, model_size: str) -> str:
    from faster_whisper import WhisperModel

    print(f"Transcrevendo (Whisper {model_size}, CPU)...")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(wav_path),
        language="pt",
        beam_size=5,
        vad_filter=True,
    )
    texto = " ".join(s.text.strip() for s in segments).strip()
    if not texto:
        raise RuntimeError("Nenhum texto reconhecido. Tente falar mais alto ou mais perto do microfone.")
    print(f"Texto reconhecido: {texto!r}")
    return texto


def conversar(thina: str, texto: str, area_id: str, timeout: float) -> dict:
    import urllib.request

    body = json.dumps({"texto": texto, "area_id": area_id}).encode()
    req = urllib.request.Request(
        f"{thina}/v1/conversar",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print("\nEnviando para Thina...")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    print(f"Resposta HTTP {resp.status} em {time.time() - t0:.1f}s")
    return data


def download_wav(thina: str, audio_url: str) -> bytes:
    import urllib.request

    if "/v1/audio/" in audio_url:
        aid = audio_url.split("/v1/audio/")[-1].split("?")[0]
        url = f"{thina}/v1/audio/{aid}"
    else:
        url = audio_url
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def play_wav_bytes(wav_bytes: bytes) -> None:
    import tempfile

    import numpy as np
    import sounddevice as sd
    from scipy.io import wavfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = Path(tmp.name)

    try:
        rate, audio = wavfile.read(tmp_path)
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        print("Reproduzindo resposta da Thina nos altifalantes do PC...")
        sd.play(audio, rate)
        sd.wait()
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Teste Thina com microfone do PC")
    p.add_argument("--area-id", default="sala", help="Cômodo em maps/areas.json (default: sala)")
    p.add_argument("--seconds", type=float, default=6.0, help="Duracao da gravacao")
    p.add_argument("--device", type=int, default=None, help="Indice do microfone (ver --list-devices)")
    p.add_argument("--whisper-model", default="base", help="Modelo faster-whisper (tiny, base, small...)")
    p.add_argument("--list-devices", action="store_true", help="Lista microfones e sai")
    p.add_argument("--skip-play", action="store_true", help="Nao reproduz no PC (so HA/ReSpeaker)")
    p.add_argument("--keep-wav", action="store_true", help="Mantem data/audio/mic_test.wav")
    p.add_argument("--texto", default="", help="Pula gravacao/STT e usa este texto")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.list_devices:
        list_input_devices()
        return 0

    settings = get_settings()
    thina = thina_base_url(settings)
    mic_wav = _ROOT / "data" / "audio" / "mic_test.wav"
    mic_wav.parent.mkdir(parents=True, exist_ok=True)

    print(f"Thina: {thina} | area_id: {args.area_id}")
    if not settings.gemini_api_key.strip():
        print("ERRO: GEMINI_API_KEY vazio no .env")
        return 1

    try:
        if args.texto.strip():
            texto = args.texto.strip()
            print(f"Texto manual: {texto!r}")
        else:
            record_wav(mic_wav, args.seconds, args.device)
            texto = transcribe(mic_wav, args.whisper_model)

        data = conversar(thina, texto, args.area_id, timeout=120.0)
        print(f"  resposta: {data.get('resposta', '')[:300]}")
        print(f"  audio_url: {data.get('audio_url')}")
        print(f"  media_player: {data.get('media_player')}")

        audio_url = data.get("audio_url", "")
        if audio_url and not args.skip_play:
            wav = download_wav(thina, audio_url)
            print(f"  wav: {len(wav)} bytes")
            play_wav_bytes(wav)
    except Exception as exc:
        print(f"FALHA: {exc}")
        return 1
    finally:
        if not args.keep_wav and mic_wav.exists() and not args.texto.strip():
            mic_wav.unlink(missing_ok=True)

    print("\nConcluido. Se o HA estiver ativo, o audio tambem foi enviado ao media_player.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
