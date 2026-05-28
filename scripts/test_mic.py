"""Teste de voz no PC com palavra de ativacao 'Tina' e resposta da Thina.

Fluxo padrao:
  1. Escuta continua ate ouvir 'Tina' / 'Thina' (Vosk, rapido)
  2. Bip duplo nos altifalantes = pronta para ouvir o pedido
  3. Grava o pedido ate voce parar de falar (silencio)
  4. Envia para Thina e reproduz a resposta
  5. Volta a escutar (modo loop)

Uso:
  .\\test-mic.ps1
  .\\test-mic.ps1 --list-devices
  .\\test-mic.ps1 --once
  .\\test-mic.ps1 --no-wake --seconds 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

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
VOSK_MODEL_DIR = _ROOT / "data" / "models" / "vosk-model-small-pt-0.3"
VOSK_ZIP_URL = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"

# Vosk PT costuma errar "Tina" — aceitar variantes comuns
WAKE_HINTS = (
    "tina",
    "thina",
    "cretina",
    "china",
    "tinha",
    "quina",
    "teena",
    "tyna",
)
WAKE_PATTERN = re.compile(
    r"\b(tina|thina|cretina|china|tinha|quina)\b", re.IGNORECASE
)
WAKE_STRIP = re.compile(
    r"^(\s*(ei|olá|ola|hey)\s+)?(tina|thina|cretina|china|tinha|quina)\s*[\s,.\-:!?]*",
    re.IGNORECASE,
)
WAKE_GRAMMAR = json.dumps(
    [
        "tina",
        "thina",
        "ei tina",
        "olá tina",
        "ola tina",
        "hey tina",
        "tina thina",
        "cretina",
        "china",
        "[unk]",
    ],
    ensure_ascii=False,
)

_vosk_model = None
_whisper_model = None
_whisper_size: str | None = None


def thina_base_url(settings) -> str:
    return f"http://127.0.0.1:{settings.thina_port}"


def list_input_devices() -> None:
    import sounddevice as sd

    print("Dispositivos de audio (entrada):")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            default = " [PADRAO]" if i == sd.default.device[0] else ""
            print(f"  [{i}] {dev['name']}{default}")


def list_output_devices() -> None:
    import sounddevice as sd

    print("Dispositivos de audio (saida):")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            default = " [PADRAO]" if i == sd.default.device[1] else ""
            print(f"  [{i}] {dev['name']}{default}")


def ensure_vosk_model() -> Path:
    if VOSK_MODEL_DIR.is_dir() and any(VOSK_MODEL_DIR.iterdir()):
        return VOSK_MODEL_DIR

    VOSK_MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    zip_path = VOSK_MODEL_DIR.parent / "vosk-model-small-pt-0.3.zip"
    print("Baixando modelo Vosk PT (~45 MB, primeira vez)...")
    urlretrieve(VOSK_ZIP_URL, zip_path)
    print("Extraindo modelo...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(VOSK_MODEL_DIR.parent)
    zip_path.unlink(missing_ok=True)
    if not VOSK_MODEL_DIR.is_dir():
        raise RuntimeError(f"Modelo Vosk nao encontrado em {VOSK_MODEL_DIR}")
    return VOSK_MODEL_DIR


def get_vosk_model():
    global _vosk_model
    if _vosk_model is None:
        from vosk import Model, SetLogLevel

        SetLogLevel(-1)
        path = ensure_vosk_model()
        print("Carregando Vosk (STT rapido)...")
        _vosk_model = Model(str(path))
    return _vosk_model


def get_whisper(model_size: str):
    global _whisper_model, _whisper_size
    if _whisper_model is None or _whisper_size != model_size:
        from faster_whisper import WhisperModel

        print(f"Carregando Whisper {model_size} (fallback)...")
        _whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _whisper_size = model_size
    return _whisper_model


def as_pcm_bytes(data) -> bytes:
    """Converte buffer do sounddevice/numpy para bytes (Vosk exige bytes, nao cffi buffer)."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if hasattr(data, "tobytes"):
        return data.tobytes()
    return bytes(memoryview(data))


def has_wake_word(text: str) -> bool:
    if not text or text.strip().lower() in ("[unk]", "unk"):
        return False
    if WAKE_PATTERN.search(text):
        return True
    lowered = text.lower()
    return any(hint in lowered for hint in WAKE_HINTS)


def strip_wake_word(text: str) -> str:
    cleaned = WAKE_STRIP.sub("", text.strip()).strip()
    if cleaned:
        return cleaned
    lowered = text.lower()
    for hint in sorted(WAKE_HINTS, key=len, reverse=True):
        idx = lowered.find(hint)
        if idx >= 0:
            return text[idx + len(hint) :].lstrip(" ,.-:!?")
    return text.strip()


def pcm_chunk_rms(chunk: bytes) -> float:
    import numpy as np

    arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))


def print_input_device(device: int | None) -> None:
    import sounddevice as sd

    idx = device if device is not None else sd.default.device[0]
    info = sd.query_devices(idx)
    print(f"  Microfone [{idx}]: {info['name']}")


def pcm_to_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)


def play_ready_beep(output_device: int | None = None) -> None:
    """Dois bips curtos: microfone pronto para o pedido (apos 'Tina')."""
    import numpy as np
    import sounddevice as sd

    gap = np.zeros(int(SAMPLE_RATE * 0.05), dtype=np.float32)
    parts: list[np.ndarray] = []
    for freq_hz, duration_s in ((880.0, 0.1), (1175.0, 0.12)):
        t = np.linspace(0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
        env = np.sin(np.pi * t / duration_s)
        tone = (0.4 * env * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
        parts.extend([tone, gap])
    audio = np.concatenate(parts)
    sd.play(audio, SAMPLE_RATE, device=output_device)
    sd.wait()


def record_until_silence(
    device: int | None,
    *,
    max_seconds: float = 8.0,
    silence_seconds: float = 1.0,
    rms_threshold: float = 0.015,
) -> bytes:
    """Grava ate detectar silencio apos fala (100 ms por bloco)."""
    import numpy as np
    import sounddevice as sd

    block_ms = 0.1
    block = int(SAMPLE_RATE * block_ms)
    max_blocks = int(max_seconds / block_ms)
    silence_blocks = int(silence_seconds / block_ms)

    chunks: list[np.ndarray] = []
    silent_run = 0
    speech_started = False

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=device,
        blocksize=block,
    ) as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(block)
            rms = float(np.sqrt(np.mean(np.square(data))))
            if rms >= rms_threshold:
                speech_started = True
                silent_run = 0
                chunks.append(data.copy())
            elif speech_started:
                chunks.append(data.copy())
                silent_run += 1
                if silent_run >= silence_blocks:
                    break

    if not chunks:
        raise RuntimeError("Nenhuma fala detectada apos 'Tina'. Fale mais perto do microfone.")

    audio = np.concatenate(chunks, axis=0).flatten()
    pcm = (audio * 32767).astype("int16").tobytes()
    return pcm


def record_fixed_seconds(seconds: float, device: int | None) -> bytes:
    import numpy as np
    import sounddevice as sd

    frames = int(seconds * SAMPLE_RATE)
    audio = sd.rec(
        frames,
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return (audio.flatten() * 32767).astype("int16").tobytes()


def transcribe_vosk_pcm(pcm: bytes, model) -> str:
    from vosk import KaldiRecognizer

    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(False)
    step = 4000
    for i in range(0, len(pcm), step):
        rec.AcceptWaveform(pcm[i : i + step])
    result = json.loads(rec.FinalResult())
    return result.get("text", "").strip()


def transcribe_whisper_wav(wav_path: Path, model_size: str) -> str:
    model = get_whisper(model_size)
    segments, _ = model.transcribe(
        str(wav_path),
        language="pt",
        beam_size=1,
        vad_filter=True,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def transcribe_pcm(pcm: bytes, wav_path: Path, *, whisper_model: str, use_vosk: bool) -> str:
    pcm_to_wav(wav_path, pcm)
    if use_vosk:
        t0 = time.time()
        text = transcribe_vosk_pcm(pcm, get_vosk_model())
        print(f"STT Vosk em {time.time() - t0:.1f}s")
        if text:
            return text
        print("Vosk vazio, tentando Whisper...")
    t0 = time.time()
    text = transcribe_whisper_wav(wav_path, whisper_model)
    print(f"STT Whisper em {time.time() - t0:.1f}s")
    if not text:
        raise RuntimeError("Nenhum texto reconhecido.")
    return text


def _wake_from_recognizer(rec, chunk: bytes) -> str | None:
    """Processa um bloco PCM; devolve frase de ativacao ou None."""
    chunk = as_pcm_bytes(chunk)
    if rec.AcceptWaveform(chunk):
        text = json.loads(rec.Result()).get("text", "").strip()
        if has_wake_word(text):
            return text
        return None
    partial = json.loads(rec.PartialResult()).get("partial", "").strip()
    if has_wake_word(partial):
        return partial
    return None


def wait_for_wake_word(device: int | None, *, verbose: bool = True) -> str | None:
    """Escuta o microfone ate detectar Tina/Thina. Retorna texto da mesma frase, se houver."""
    import sounddevice as sd
    from vosk import KaldiRecognizer

    model = get_vosk_model()
    print("\nDiga 'Tina' para eu ouvir... (Ctrl+C para sair)")
    print("  Dica: fale claro e perto do microfone; pausa 0,5 s depois do nome.")
    if verbose:
        print("  (mostrando o que o Vosk ouve — use --quiet para ocultar)")

    block_samples = 4000
    last_ui = time.time()
    silent_since = time.time()
    last_partial = ""

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=block_samples,
        dtype="int16",
        channels=CHANNELS,
        device=device,
    ) as stream:
        # Gramatica restrita melhora muito o reconhecimento de "tina"
        rec_wake = KaldiRecognizer(model, SAMPLE_RATE)
        try:
            rec_wake.SetGrammar(WAKE_GRAMMAR)
        except Exception:
            print("  AVISO: SetGrammar indisponivel; usando reconhecimento aberto.")
        rec_open = KaldiRecognizer(model, SAMPLE_RATE)

        while True:
            data, _ = stream.read(block_samples)
            chunk = as_pcm_bytes(data)
            rms = pcm_chunk_rms(chunk)
            now = time.time()

            if rms >= 0.008:
                silent_since = now
            elif now - silent_since > 8 and verbose:
                print("  AVISO: sem sinal no microfone — verifique volume/dispositivo (--list-devices).")
                silent_since = now

            hit = _wake_from_recognizer(rec_wake, chunk) or _wake_from_recognizer(rec_open, chunk)
            if hit:
                print(f"  Ativacao: {hit!r}")
                return hit

            if verbose:
                partial = json.loads(rec_open.PartialResult()).get("partial", "").strip()
                if partial and partial != last_partial:
                    print(f"  ouvindo: {partial!r}")
                    last_partial = partial
                elif now - last_ui >= 2.0:
                    bar = "#" * min(20, int(rms * 400))
                    print(f"  [mic {rms:.3f}] {bar or '.'}")
                    last_ui = now


def capture_command_after_wake(
    wake_phrase: str | None,
    device: int | None,
    wav_path: Path,
    *,
    whisper_model: str,
    output_device: int | None = None,
) -> str:
    """Extrai comando da frase de ativacao ou grava ate silencio."""
    if wake_phrase:
        cmd = strip_wake_word(wake_phrase)
        if len(cmd) >= 3:
            print(f"Pedido (mesma frase): {cmd!r}")
            return cmd

    play_ready_beep(output_device)
    print("Pode falar agora.")
    pcm = record_until_silence(device)
    pcm_to_wav(wav_path, pcm)
    print(f"Gravacao: {len(pcm)} bytes (~{len(pcm) / 2 / SAMPLE_RATE:.1f}s)")
    text = transcribe_pcm(pcm, wav_path, whisper_model=whisper_model, use_vosk=True)
    print(f"Texto reconhecido: {text!r}")
    return text


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
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    with resp:
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


def play_wav_bytes(wav_bytes: bytes, output_device: int | None = None) -> None:
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
        print("Reproduzindo resposta...")
        sd.play(audio, rate, device=output_device)
        sd.wait()
    finally:
        tmp_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Teste Thina com microfone (wake word Tina)")
    p.add_argument("--area-id", default="sala", help="Cômodo em maps/areas.json")
    p.add_argument("--device", type=int, default=None, help="Indice do microfone")
    p.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="Indice dos altifalantes (bip de pronto + resposta)",
    )
    p.add_argument("--whisper-model", default="tiny", help="Whisper fallback (tiny=mais rapido)")
    p.add_argument("--list-devices", action="store_true", help="Lista microfones")
    p.add_argument("--skip-play", action="store_true", help="Nao reproduz no PC")
    p.add_argument("--keep-wav", action="store_true", help="Mantem data/audio/mic_test.wav")
    p.add_argument("--texto", default="", help="Pula microfone e usa este texto")
    p.add_argument(
        "--no-wake",
        action="store_true",
        help="Modo antigo: grava N segundos fixos sem esperar 'Tina'",
    )
    p.add_argument("--seconds", type=float, default=6.0, help="Com --no-wake: duracao fixa")
    p.add_argument("--once", action="store_true", help="Uma interacao e sai (padrao: loop)")
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Sem feedback 'ouvindo' / nivel do microfone",
    )
    return p.parse_args()


def run_interaction(
    args: argparse.Namespace,
    thina: str,
    mic_wav: Path,
) -> bool:
    """Uma rodada completa. Retorna False se deve parar o loop."""
    t_total = time.time()

    if args.texto.strip():
        texto = args.texto.strip()
        print(f"Texto manual: {texto!r}")
    elif args.no_wake:
        print(f"\nGravando {args.seconds:.0f}s (sem wake word)...")
        pcm = record_fixed_seconds(args.seconds, args.device)
        texto = transcribe_pcm(
            pcm, mic_wav, whisper_model=args.whisper_model, use_vosk=True
        )
        print(f"Texto reconhecido: {texto!r}")
    else:
        wake = wait_for_wake_word(args.device, verbose=not args.quiet)
        texto = capture_command_after_wake(
            wake,
            args.device,
            mic_wav,
            whisper_model=args.whisper_model,
            output_device=args.output_device,
        )

    data = conversar(thina, texto, args.area_id, timeout=120.0)
    print(f"  resposta: {data.get('resposta', '')[:300]}")
    print(f"  audio_url: {data.get('audio_url')}")
    print(f"  media_player: {data.get('media_player')}")

    audio_url = data.get("audio_url", "")
    if audio_url and not args.skip_play:
        wav = download_wav(thina, audio_url)
        print(f"  wav: {len(wav)} bytes")
        play_wav_bytes(wav, args.output_device)

    print(f"\nTempo total desta rodada: {time.time() - t_total:.1f}s")
    return True


def main() -> int:
    args = parse_args()

    if args.list_devices:
        list_input_devices()
        print()
        list_output_devices()
        return 0

    settings = get_settings()
    thina = thina_base_url(settings)
    mic_wav = _ROOT / "data" / "audio" / "mic_test.wav"
    mic_wav.parent.mkdir(parents=True, exist_ok=True)

    print(f"Thina: {thina} | area_id: {args.area_id} | voz: {settings.kokoro_voice}")
    if not args.no_wake and not args.texto.strip():
        print("Modo: diga 'Tina' e em seguida seu pedido (para no silencio).")
        print_input_device(args.device)
    if not settings.llm_api_key_configured():
        key_name = "DEEPSEEK_API_KEY" if settings.llm_provider == "deepseek" else "GEMINI_API_KEY"
        print(f"ERRO: {key_name} vazio no .env (LLM_PROVIDER={settings.llm_provider})")
        return 1

    try:
        if not args.no_wake and not args.texto.strip():
            get_vosk_model()

        while True:
            run_interaction(args, thina, mic_wav)
            if args.once or args.texto.strip():
                break
            print("\n--- Aguardando 'Tina' de novo ---")
    except KeyboardInterrupt:
        print("\nEncerrado.")
        return 0
    except Exception as exc:
        print(f"FALHA: {exc}")
        return 1
    finally:
        if not args.keep_wav and mic_wav.exists() and not args.texto.strip():
            mic_wav.unlink(missing_ok=True)

    print("\nConcluido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
