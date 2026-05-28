"""Teste rapido dos servicos Thina + Kokoro + HA."""

from __future__ import annotations



import json

import sys

import time

import urllib.error

import urllib.request

from pathlib import Path



# Permite importar config.py da raiz do projeto

_ROOT = Path(__file__).resolve().parents[1]

if str(_ROOT) not in sys.path:

    sys.path.insert(0, str(_ROOT))



from config import get_settings  # noqa: E402





def get(url: str, timeout: float = 10) -> tuple[int, bytes]:

    r = urllib.request.urlopen(url, timeout=timeout)

    return r.status, r.read()





def post(url: str, data: dict, timeout: float = 120) -> tuple[int, bytes]:

    body = json.dumps(data).encode()

    req = urllib.request.Request(

        url,

        data=body,

        headers={"Content-Type": "application/json"},

        method="POST",

    )

    r = urllib.request.urlopen(req, timeout=timeout)

    return r.status, r.read()





def thina_base_url(settings) -> str:

    """URL local para testes (evita conflito WSL em 127.0.0.1:8080)."""

    return f"http://127.0.0.1:{settings.thina_port}"





def main() -> int:

    settings = get_settings()

    thina = thina_base_url(settings)

    ok = True



    print(f"Config: Thina {thina} | Kokoro {settings.kokoro_server_url} | HA {settings.home_assistant_url}")

    if not settings.home_assistant_token.strip():

        print("AVISO: HOME_ASSISTANT_TOKEN vazio no .env")

    if not settings.gemini_api_key.strip():

        print("AVISO: GEMINI_API_KEY vazio no .env")



    print("\n=== Thina /health ===")

    try:

        status, body = get(f"{thina}/health")

        print(f"OK HTTP {status}: {body.decode()}")

    except Exception as exc:

        ok = False

        print(f"FALHA: {exc}")



    print("\n=== Kokoro /voices ===")

    try:

        status, body = get(f"{settings.kokoro_server_url}/voices")

        voices = json.loads(body.decode()).get("voices", [])

        print(f"OK HTTP {status}: {len(voices)} vozes")

    except Exception as exc:

        ok = False

        print(f"FALHA: {exc}")



    print("\n=== Home Assistant ===")

    try:

        status, _ = get(f"{settings.home_assistant_url}/", timeout=15)

        print(f"OK HTTP {status}")

    except urllib.error.HTTPError as exc:

        print(f"OK HTTP {exc.code} (pagina/login)")

    except Exception as exc:

        ok = False

        print(f"FALHA: {exc}")



    print("\n=== POST /v1/conversar ===")

    t0 = time.time()

    try:

        status, body = post(

            f"{thina}/v1/conversar",

            {

                "texto": "ola thina, responda em uma frase curta de boas vindas.",

                "area_id": "sala",

            },

        )

        data = json.loads(body.decode())

        elapsed = time.time() - t0

        print(f"OK HTTP {status} em {elapsed:.1f}s")

        print(f"  resposta: {data.get('resposta', '')[:200]}")

        print(f"  audio_url: {data.get('audio_url')}")

        print(f"  media_player: {data.get('media_player')}")



        audio_url = data.get("audio_url", "")

        if "/v1/audio/" in audio_url:

            aid = audio_url.split("/v1/audio/")[-1]

            _, wav = get(f"{thina}/v1/audio/{aid}", timeout=15)

            print(f"  wav: {len(wav)} bytes")

    except urllib.error.HTTPError as exc:

        elapsed = time.time() - t0

        ok = False

        print(f"HTTP {exc.code} em {elapsed:.1f}s")

        print(exc.read().decode()[:400])

    except Exception as exc:

        ok = False

        print(f"FALHA: {exc}")



    return 0 if ok else 1





if __name__ == "__main__":

    sys.exit(main())

