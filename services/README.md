# Shims legados (`services/`)

**Não implemente lógica aqui.** Este pacote só reexporta módulos em `thina/` para imports e subprocessos antigos.

| Shim | Implementação |
|------|----------------|
| `services.gemini_mcp` | `thina.llm.gemini_mcp` |
| `services.ha_client` | `thina.integrations.homeassistant` |
| `services.tts_kokoro` | `thina.integrations.kokoro` |
| `services.deepseek_llm` | `thina.llm.deepseek` |
| `services.conversation_store` | `thina.core.conversation` |
| `services.thina_context` | `thina.context.user` |
| `services.texto_voz` | `thina.speech.normalize` |
| `services.pc_actions` | `thina.pc.actions` |
| `services.spotify_pc` | `thina.pc.spotify` |
| `config` (raiz) | `thina.core.config` |

Código novo: `from thina...` e `MCP_SERVER_MODULE=thina.llm.gemini_mcp` (padrão no `.env`).
