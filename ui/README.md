# Thina — Interface WebGL

Painel visual para a Thina: núcleo de partículas WebGL2, estados (aguardando, ouvindo, pensando, respondendo) e integração com `POST /v1/conversar`.

## Desenvolvimento

```powershell
cd ui
npm install
npm run dev
```

Abre **`http://localhost:5173/ui/`** (com `/ui/` no final).

O Vite faz proxy de `/health` e `/v1` para `http://127.0.0.1:<THINA_PORT>` lendo `THINA_PORT` do `.env` na raiz do repo (padrão `8080`). No Windows, se `8080` responder 404 (conflito WSL), use `THINA_PORT=8081` no `.env`.

Deixe **URL do servidor vazia** nas configurações da UI (usa URLs relativas + proxy).

## Produção (servido pelo FastAPI)

```powershell
cd ui
npm install
npm run build
```

Reinicie o servidor Thina e acesse `http://127.0.0.1:8080/` (redireciona para `/ui/`).

## Comandos na interface

| Ação | Efeito |
|------|--------|
| **Ativar / Parar Thina** | Alterna escuta, sessão e pedido em curso |
| **Microfone ao abrir** | Ativa a Thina automaticamente quando o servidor responde |
| **Manter conversa ativa** | Reutiliza `session_id` nos envios seguintes |
| **Enviar** | Chama `/v1/conversar` com o `area_id` configurado |

Configurações ficam em `localStorage` (URL do servidor, cômodo, reproduzir áudio no browser).
