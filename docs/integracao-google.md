# Integração Google (Gmail, Drive, Calendar)

A Thina acessa sua conta Google via OAuth2: ler emails, abrir arquivos no Drive, criar eventos na agenda e enviar emails.

> Pré-requisito: Thina instalada — [instalacao.md](./instalacao.md).

## 1. Google Cloud Console

1. Crie um projeto (ou use um existente) em [Google Cloud Console](https://console.cloud.google.com/).
2. Ative as APIs:
   - Gmail API
   - Google Drive API
   - Google Calendar API
3. **OAuth consent screen**: tipo *External* (ou Internal se for Workspace), adicione seu email como test user se estiver em modo teste.
4. **Credentials** → *Create credentials* → *OAuth client ID* → tipo **Desktop app**.
5. Baixe o JSON e salve como `data/google_credentials.json` na raiz do repositório.

## 2. Configurar o `.env`

```env
GOOGLE_ENABLED=true
# GOOGLE_TIMEZONE=America/Sao_Paulo
# GOOGLE_CREDENTIALS_FILE=data/google_credentials.json
# GOOGLE_TOKEN_FILE=data/google_token.json
```

## 3. Autorizar a conta

No **host** onde você edita arquivos do projeto (não dentro do container). Com venv do instalador:

Windows:

```powershell
.\.venv\Scripts\python scripts/google_auth.py
```

macOS / Linux:

```bash
.venv/bin/python scripts/google_auth.py
```

Se as permissões mudarem (ex.: de somente leitura para enviar email/criar eventos):

```powershell
# Windows
.\.venv\Scripts\python scripts/google_auth.py --force
```

```bash
# macOS / Linux
.venv/bin/python scripts/google_auth.py --force
```

O navegador abre para você conceder acesso. O token fica em `data/google_token.json` (gitignore).

**Stack Docker:** gere o token no host (comandos acima). Para o container enxergar os ficheiros, adicione volumes em `docker-compose.yml` (serviço `thina`):

```yaml
      - ./data/google_credentials.json:/app/data/google_credentials.json
      - ./data/google_token.json:/app/data/google_token.json
```

Reinicie: `docker compose restart thina`. No Windows, alternativa guiada: `.\scripts\setup_google.ps1`.

## 4. O que você pode pedir por voz

| Ação | Exemplo |
|------|---------|
| Ler emails | *"Tenho email novo no Gmail?"* / *"Lê o último email"* |
| Abrir Drive | *"Abre o arquivo X do Drive"* |
| Ler conteúdo | *"O que tem no documento Y?"* |
| Ver agenda | *"O que tenho na agenda amanhã?"* |
| Criar evento | *"Marca dentista segunda às 15h"* |
| Enviar email | *"Manda email pro fulano dizendo..."* |

## Ferramentas MCP

| Ferramenta | Função |
|------------|--------|
| `listar_emails_gmail` | Lista emails |
| `ler_email_gmail` | Lê email completo |
| `marcar_email_lido` | Marca como lido |
| `enviar_email_gmail` | Envia email |
| `listar_arquivos_drive` | Lista arquivos |
| `ler_arquivo_drive` | Lê texto do arquivo |
| `abrir_arquivo_drive` | Abre no navegador |
| `listar_eventos_agenda` | Próximos eventos |
| `criar_evento_agenda` | Cria evento |

## Permissões (scopes)

| Serviço   | Escopo              | Permite |
|-----------|---------------------|---------|
| Gmail     | `gmail.modify`      | Ler, enviar, marcar lido |
| Drive     | `drive.readonly`    | Listar, ler, abrir links |
| Calendar  | `calendar.events`   | Criar e gerenciar eventos |

## Segurança

- `data/google_credentials.json` e `data/google_token.json` **não** vão para o Git.
- A Thina confirma antes de enviar email ou criar evento se o pedido for ambíguo.
- Revogue o acesso em [Conta Google → Segurança → Acesso de terceiros](https://myaccount.google.com/permissions) se necessário.
