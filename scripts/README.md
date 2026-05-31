# Scripts operacionais

Implementação real fica aqui; **atalhos na raiz** do repo delegam para estes arquivos (URLs estáveis na documentação).

## Docker (stack HA + Kokoro + Thina)

| Ação | Raiz | Script |
|------|------|--------|
| Subir / build | `start-docker.ps1` / `start-docker.sh` | `lib/docker-stack.*` |
| Parar | `stop-docker.ps1` / `stop-docker.sh` | idem |
| Reiniciar | `restart-docker.ps1` / `restart-docker.sh` | `restart-docker.ps1` (Win) |

## Modo nativo Windows (dev, comandos de PC)

| Ação | Raiz | Script |
|------|------|--------|
| Subir | `start.ps1` | `start-services.ps1` |
| Parar | `stop.ps1` | `stop-services.ps1` |
| Reiniciar | `restart.ps1` | `restart-services.ps1` |
| Status | — | `status-services.ps1` |

## Instalação e integrações

| Script | Uso |
|--------|-----|
| `../install.ps1` / `../install.sh` | Primeira instalação |
| `setup_google.ps1` / `setup_google.sh` | OAuth Google (ou `configurar-google.bat` na raiz) |
| `google_auth.py` | Fluxo OAuth manual |
| `test_app.py` | Teste integrado `/v1/conversar` |
| `test_mic.py` | Teste microfone (`../test-mic.ps1` na raiz) |

Ver [AGENTS.md](../AGENTS.md) e [docs/README.md](../docs/README.md).
