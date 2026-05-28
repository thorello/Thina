"""Testes da normalizacao de texto para TTS."""

from __future__ import annotations

import pytest

from thina.speech.normalize import preparar_texto_para_voz


@pytest.mark.parametrize(
    ("entrada", "esperado_contem"),
    [
        ("", ""),
        ("  ola  ", "ola"),
        ("**negrito**", "negrito"),
        ("*italico*", "italico"),
        ("[link](https://exemplo.com)", "link"),
        ("# Titulo\nparagrafo", "paragrafo"),
        ("- item lista", "item lista"),
        ("`codigo`", "codigo"),
    ],
)
def test_preparar_texto_para_voz(entrada: str, esperado_contem: str) -> None:
    resultado = preparar_texto_para_voz(entrada)
    if not entrada.strip():
        assert resultado == entrada or resultado == ""
        return
    assert esperado_contem in resultado
    assert "**" not in resultado
    assert "`" not in resultado


def test_remove_emojis() -> None:
    texto = "Tocando musica 🎵 agora"
    resultado = preparar_texto_para_voz(texto)
    assert "🎵" not in resultado
    assert "Tocando" in resultado


def test_colapsa_espacos_duplicados() -> None:
    assert preparar_texto_para_voz("ola    mundo") == "ola mundo"
