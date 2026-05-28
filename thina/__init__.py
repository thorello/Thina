"""
Pacote principal do servidor Thina (assistente de voz residencial).

Estrutura semantica:
  api/           — FastAPI (rotas HTTP)
  core/          — config, sessoes de conversa
  context/       — personalidade e mapas do usuario
  speech/        — normalizacao de texto para TTS
  integrations/  — Home Assistant, Kokoro
  llm/           — Gemini/DeepSeek + servidor MCP
  pc/            — apps e Spotify no Windows
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
