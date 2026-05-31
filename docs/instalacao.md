# Instalação — Thina (Docker)

Guia passo a passo para subir a stack completa (**Home Assistant + Kokoro TTS + Thina**) com Docker.

| Plataforma | Caminho recomendado |
|------------|---------------------|
| **Windows** | Docker Desktop ou Docker no WSL → [`start-docker.ps1`](#windows-com-docker) |
| **macOS** | Docker Desktop → [`start-docker.sh`](#mac-com-docker) |

Modo nativo Windows (sem Docker para Thina/Kokoro, com comandos de PC) é documentado na [seção avançada](#avançado-modo-nativo-windows).

---

## Pré-requisitos

- **Git** com suporte a submódulos
- **Docker** com Compose v2 (`docker compose version`)
- ~**4 GB RAM** livres para os containers (Kokoro carrega modelos de voz)
- Chave de LLM: `DEEPSEEK_API_KEY` ou `GEMINI_API_KEY`

Clone o repositório **com submódulos** (inclui o Kokoro TTS):

```bash
git clone --recurse-submodules https://github.com/thorello/Thina.git
cd Thina
```

Se já clonou sem submódulos:

```bash
git submodule update --init --recursive
```

---

## Windows com Docker

### Escolha o Docker

| | Docker Desktop | Docker só no WSL |
|--|----------------|------------------|
| Onde roda `docker` | PowerShell / CMD nativo | Dentro da distro WSL (ex.: Ubuntu) |
| Instalação | [Docker Desktop para Windows](https://docs.docker.com/desktop/setup/install/windows-install/) com backend WSL2 | [Docker Engine no WSL](https://docs.docker.com/engine/install/) |
| Config extra | Nenhuma | `DOCKER_VIA_WSL=true` no `.env` |
| Repo em disco Windows | Sim (`G:\git\Thina`, etc.) | Sim — scripts traduzem path via `wslpath` |

Na maioria dos casos, **Docker Desktop** é o caminho mais simples.

### Passos

**1. Instalar dependências do projeto**

```powershell
.\install.ps1
```

Para pular venvs Python (só Docker):

```powershell
.\install.ps1 -DockerOnly
```

**2. Configurar `.env`**

O instalador cria `.env` a partir de `.env.example`. Edite pelo menos:

| Variável | O que preencher |
|----------|-----------------|
| `DEEPSEEK_API_KEY` ou `GEMINI_API_KEY` | Chave do provedor LLM |
| `LLM_PROVIDER` | `deepseek` ou `gemini` |
| `TZ` | Fuso horário (ex.: `America/Sao_Paulo`) |
| `THINA_DEFAULT_CITY` | Cidade padrão para clima (opcional) |

No modo Docker unificado, `THINA_PUBLIC_URL`, `KOKORO_SERVER_URL` e `HOME_ASSISTANT_URL` já são definidos no [`docker-compose.yml`](../docker-compose.yml) — não precisa alterá-los na primeira instalação.

**3. Subir a stack (primeira vez com build)**

```powershell
.\start-docker.ps1 -Build
```

Nas execuções seguintes, basta `.\start-docker.ps1`. O script detecta imagens ausentes e faz build automaticamente na primeira vez.

**4. Configurar o Home Assistant**

1. Abra http://localhost:8123
2. Crie o utilizador na primeira visita (onboarding)
3. Gere um **token de longa duração**: *Perfil → Segurança → Tokens de acesso de longa duração*
4. Cole o token em `HOME_ASSISTANT_TOKEN` no `.env`
5. Reinicie o container Thina para carregar o token:

```powershell
docker compose restart thina
```

**5. Verificar**

| Serviço | URL |
|---------|-----|
| Home Assistant | http://localhost:8123 |
| Kokoro TTS | http://localhost:8000/voices |
| Thina API | http://localhost:8080/health |
| Painel UI | http://localhost:8080/ui/ |

```powershell
curl http://localhost:8080/health
```

Deve retornar `{"status":"ok","service":"thina"}`.

### Docker via WSL (sem Docker Desktop)

1. Instale uma distro WSL (ex.: Ubuntu) e o Docker Engine dentro dela
2. No `.env`, descomente ou adicione:

```env
DOCKER_VIA_WSL=true
WSL_DISTRO=Ubuntu
```

3. Use os mesmos comandos PowerShell (`.\start-docker.ps1 -Build`) — o script [`scripts/lib/docker-stack.ps1`](../scripts/lib/docker-stack.ps1) executa `docker compose` dentro do WSL

Se moveu o WSL para outro disco, rode `wsl --shutdown` antes de subir a stack.

### Notas Windows

- **`PC_COMMANDS_ENABLED`** (abrir Chrome, Spotify, etc.) **não funciona** dentro do container Docker. Use o [modo nativo](#avançado-modo-nativo-windows) se precisar controlar o PC.
- Conflito de porta **8080** com `wslrelay` afeta sobretudo o **modo nativo**. Na stack Docker, a porta 8080 costuma funcionar normalmente.

---

## Mac com Docker

### Passos

**1. Instalar Docker Desktop**

[Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/) (Apple Silicon e Intel).

**2. Instalar dependências do projeto**

```bash
chmod +x install.sh start-docker.sh stop-docker.sh restart-docker.sh
./install.sh --docker-only
```

**3. Configurar `.env`**

Mesmas variáveis da [tabela Windows](#2-configurar-env) (`DEEPSEEK_API_KEY` / `GEMINI_API_KEY`, etc.).

**4. Subir a stack (primeira vez com build)**

```bash
./start-docker.sh --build
```

Nas execuções seguintes: `./start-docker.sh` (build automático se imagens não existirem).

**5. Home Assistant e verificação**

Igual ao [passo 4 e 5 do Windows](#4-configurar-o-home-assistant): onboarding em `:8123`, token no `.env`, `docker compose restart thina`, healthcheck em `:8080/health`.

Apple Silicon (M1/M2/M3): as imagens são construídas localmente a partir do [`Dockerfile`](../Dockerfile) — não há passo extra na instalação padrão.

---

## Configuração pós-instalação

### Contexto privado e personalidade

O instalador copia `maps/private.example` → `maps/private/` (gitignore). Edite os `.md` com dados sobre você, a casa e rotinas.

Tom da Thina: [`maps/thina_user.md`](../maps/thina_user.md) (pode ir no Git).

### Mapa de cômodos

Edite [`maps/areas.json`](../maps/areas.json):

```json
{
  "sala": "media_player.respeaker_sala",
  "quarto": "media_player.respeaker_quarto"
}
```

O `area_id` enviado pelo Home Assistant deve corresponder a uma chave deste ficheiro.

### `THINA_PUBLIC_URL`

| Modo | Valor |
|------|-------|
| Stack Docker unificada (este guia) | `http://thina:8080` — já definido no compose; o HA baixa o WAV pela rede interna Docker |
| HA externo (noutro host) | URL que o **HA** alcança, ex.: `http://192.168.1.50:8080` |

### Próximos passos

- **ReSpeaker / voz por cômodo:** [integracao-respeaker-lite.md](./integracao-respeaker-lite.md)
- **Gmail, Drive, Calendar:** [integracao-google.md](./integracao-google.md) — quem usa: duplo clique em `configurar-google.bat` (Windows) ou `./scripts/setup_google.sh`

---

## Operação do dia a dia

| Ação | Windows | Mac / Linux |
|------|---------|-------------|
| Subir | `.\start-docker.ps1` | `./start-docker.sh` |
| Parar | `.\stop-docker.ps1` | `./stop-docker.sh` |
| Rebuild completo | `.\start-docker.ps1 -Build` ou `.\restart-docker.ps1` | `./start-docker.sh --build` ou `./restart-docker.sh` |
| Status | `docker compose ps` | `docker compose ps` |
| Logs Thina | `docker compose logs -f thina` | idem |
| Logs Kokoro | `docker compose logs -f kokoro` | idem |

Config persistente do Home Assistant: `data/homeassistant/`.

---

## Troubleshooting

### Kokoro vazio ou erro de build

```bash
git submodule update --init --recursive
```

Ou rode o instalador de novo (`.\install.ps1` / `./install.sh`).

### Build lento na primeira vez

Normal. O Dockerfile compila a UI (`npm ci` + build) e o Kokoro baixa dependências/modelos.

### Thina responde em `/health` mas não controla a casa

- Verifique `HOME_ASSISTANT_TOKEN` no `.env`
- Reinicie: `docker compose restart thina`
- Confirme que o HA está acessível de dentro do container: `docker compose exec thina python -c "import urllib.request; print(urllib.request.urlopen('http://homeassistant:8123').status)"`

### Portas em uso

| Porta | Serviço |
|-------|---------|
| 8123 | Home Assistant |
| 8000 | Kokoro |
| 8080 | Thina API + UI |

Altere no `.env`: `HA_HOST_PORT`, `KOKORO_HOST_PORT`, `THINA_PORT` (e ajuste mapeamento no compose se necessário).

### `docker compose` não encontrado

Instale Docker Desktop ou Docker Engine com plugin Compose v2. Comando legado: `docker-compose` também é detectado pelos scripts shell.

---

## Avançado: modo nativo Windows

Para **desenvolvimento** ou **comandos no PC** (`PC_COMMANDS_ENABLED=true`):

```powershell
.\install.ps1
.\start.ps1
```

- Home Assistant sobe via Docker **no WSL** (`scripts/ha/docker-compose.yml`)
- Kokoro e Thina rodam como processos Python no Windows
- UI de desenvolvimento: http://127.0.0.1:5173/ui/
- `THINA_PUBLIC_URL`: `http://host.docker.internal:<THINA_PORT>` (HA no Docker WSL)

Requisitos: WSL com `docker` funcional (`wsl docker version`). Para desativar HA gerido: `HOME_ASSISTANT_MANAGED=false`.

**Conflito porta 8080:** no Windows, `localhost:8080` pode ser capturado pelo `wslrelay`. Use `THINA_PORT=8081` no `.env`. Detalhes: [relatorio-fluxo-servicos.md](./relatorio-fluxo-servicos.md).

Parar / status:

```powershell
.\stop.ps1
.\scripts\status-services.ps1
```
