# Thina — Servidor central do assistente de voz residencial

Servidor Python (FastAPI) que recebe texto do Home Assistant (após STT local com Whisper), processa com **Gemini 1.5 Flash** e ferramentas **MCP** para controlar a casa, sintetiza a resposta com **Kokoro TTS** e reproduz o áudio no **ReSpeaker** do cômodo de origem.

## Arquitetura

```
Home Assistant (Whisper STT)
        │ POST /v1/conversar { texto, area_id }
        ▼
   Servidor Thina (:8080)
        ├─► Gemini 1.5 Flash + MCP (tools → HA REST)
        ├─► Kokoro TTS (:8000) → WAV
        └─► HA media_player.play_media → ReSpeaker do cômodo
```

## Pré-requisitos

- Python 3.10+
- [Kokoro TTS](https://github.com/seu-usuario/kokoro) rodando (ex.: `http://localhost:8000`)
- Home Assistant com token de longa duração
- Chave da API Gemini (`GEMINI_API_KEY`)

## Instalação

```powershell
cd thina-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edite .env com suas chaves e URLs
```

## Configuração

### Variáveis importantes

| Variável | Descrição |
|----------|-----------|
| `GEMINI_API_KEY` | Chave Google AI / Gemini |
| `HOME_ASSISTANT_URL` | URL do HA (sem barra final) |
| `HOME_ASSISTANT_TOKEN` | Token de acesso long-lived |
| `KOKORO_SERVER_URL` | URL do servidor Kokoro (ex. `http://localhost:8000`) |
| `KOKORO_VOICE` | Voz principal (`thina_mix` = media de `pf_dora` + `if_sara` no repo Kokoro) |
| `KOKORO_MIX_VOICE` / `KOKORO_MIX_AMOUNT` | Mistura manual opcional (ex. `pf_dora` + `if_sara` a `0.5`) |
| `THINA_PUBLIC_URL` | URL **acessível pelo host do HA** para baixar o WAV (não use `localhost` se o HA estiver noutra máquina/Docker) |
| `PC_COMMANDS_ENABLED` | `true` para abrir apps/sites no **PC onde o thina-server roda** (lista branca em `maps/pc_apps.json`) |
| `PC_APPS_MAP_FILE` | Caminho do mapa de aplicativos permitidos (padrão: `maps/pc_apps.json`) |

### Comandos no PC (Chrome, Spotify, etc.)

Com `PC_COMMANDS_ENABLED=true`, a Thina pode abrir programas no Windows do host do servidor — por exemplo: *“Thina, abre o Google Chrome”* ou *“abre o Spotify”*.

- Só funcionam apps listados em [`maps/pc_apps.json`](maps/pc_apps.json) (segurança: lista branca, sem comando arbitrário).
- O servidor Thina precisa rodar **na mesma máquina** que você quer controlar (não num Raspberry Pi remoto sem área de trabalho).
- Para adicionar um app, edite o JSON com `windows_cmd` ou `windows_path` e reinicie o servidor (ou recarregue o processo).

### Mapa de cômodos

Edite [`maps/areas.json`](maps/areas.json):

```json
{
  "sala": "media_player.respeaker_sala",
  "quarto": "media_player.respeaker_quarto"
}
```

O `area_id` enviado pelo HA deve corresponder a uma chave deste ficheiro.

## Executar

### Stack completa (Kokoro + Thina)

Na raiz do projeto:

```powershell
.\start.ps1          # sobe Kokoro (:8000) e Thina (THINA_PORT no .env)
.\stop.ps1           # para ambos
.\scripts\status-services.ps1
```

Ou:

```powershell
.\scripts\start-services.ps1
.\scripts\stop-services.ps1
```

Logs dos processos: `data/run/kokoro.*.log`, `data/run/thina.*.log`.

O **Home Assistant** nao e iniciado por estes scripts (corre no Docker ou noutro host).

### Apenas o servidor Thina

```powershell
.\.venv\Scripts\python main.py
```

Ou:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8080
```

Healthcheck: `GET http://localhost:<THINA_PORT>/health`

## API

### `POST /v1/conversar`

```json
{
  "texto": "liga a luz da sala",
  "area_id": "sala",
  "session_id": null
}
```

Resposta:

```json
{
  "resposta": "Pronto, liguei a luz da sala.",
  "audio_url": "http://192.168.1.100:8080/v1/audio/abc123.wav",
  "area_id": "sala",
  "media_player": "media_player.respeaker_sala"
}
```

### `GET /v1/audio/{audio_id}.wav`

Serve o ficheiro WAV para o Home Assistant usar em `play_media`.

## Integração Home Assistant

Em `configuration.yaml`:

```yaml
rest_command:
  thina_conversar:
    url: "http://192.168.1.100:8080/v1/conversar"
    method: POST
    headers:
      Content-Type: application/json
    payload: '{"texto": "{{ texto }}", "area_id": "{{ area }}"}'
```

Exemplo de automação após STT (ajuste triggers e variáveis ao seu pipeline):

```yaml
automation:
  - alias: Thina - processar voz
    triggers:
      - trigger: event
        event_type: thina_stt_ready
    actions:
      - action: rest_command.thina_conversar
        data:
          texto: "{{ trigger.event.data.text }}"
          area: "{{ trigger.event.data.area_id }}"
```

**Rede:** `THINA_PUBLIC_URL` deve ser o IP/hostname que o **Home Assistant** usa para descarregar o WAV (ex. `http://192.168.1.50:8080`), não o endereço visto apenas no PC do Thina.

## Ferramentas MCP (Gemini)

| Tool | Função |
|------|--------|
| `controlar_dispositivo` | Chama qualquer serviço HA |
| `ler_sensor` | Lê estado de uma entidade |
| `listar_entidades` | Lista entidades por domínio/área |
| `ligar_desligar` | Atalho turn_on / turn_off |

Testar o servidor MCP isolado:

```powershell
python -m services.gemini_mcp
```

## Testes manuais

```powershell
curl http://localhost:8080/health

curl -X POST http://localhost:8080/v1/conversar `
  -H "Content-Type: application/json" `
  -d '{"texto":"ola thina","area_id":"sala"}'
```

## Estrutura do projeto

```
thina-server/
├── main.py
├── config.py
├── requirements.txt
├── maps/areas.json
├── data/audio/
└── services/
    ├── ha_client.py
    ├── gemini_mcp.py
    └── tts_kokoro.py
```

## Notas

- Usa `google-genai` (não `google-generativeai`) por suporte nativo a MCP no Gemini.
- Cada requisição `/v1/conversar` inicia um subprocess MCP stdio (isolado e simples).
- Áudios em `data/audio/` são limpos após `AUDIO_RETENTION_HOURS` (padrão 24 h).
