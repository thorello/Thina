# Integração Google (Gmail, Drive, Calendar)

A Thina acessa Gmail, Drive e Agenda via OAuth2.

> Pré-requisito: Thina instalada — [instalacao.md](./instalacao.md).

---

## Para quem vai usar (sem conhecimento técnico)

Depois que quem instalou a Thina terminou a configuração, **só precisa disto**:

### Windows

1. Dê **duplo clique** em `configurar-google.bat` na pasta do projeto  
   **ou** execute `.\scripts\setup_google.ps1`
2. Abre uma página no navegador — clique em **Conectar conta Google**
3. Entre com sua conta Gmail e toque em **Permitir**
4. Pronto. Teste por voz: *"Thina, tenho email novo no Gmail?"*

### Mac / Linux

```bash
chmod +x scripts/setup_google.sh
./scripts/setup_google.sh
```

Siga os passos na página que abrir no navegador.

### Link direto (se a Thina já estiver rodando)

Abra no navegador: **http://localhost:8080/v1/google/setup**

---

## Para quem instala (uma vez por casa)

O Google exige um **aplicativo OAuth** no Cloud Console. Faça isto **uma vez**; depois pode copiar o mesmo `.env` (ou o JSON) para outras instalações da mesma casa.

### 1. Google Cloud Console

1. [Google Cloud Console](https://console.cloud.google.com/) → crie um projeto (ex.: `Thina Casa`)
2. Ative as APIs:
   - [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
   - [Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
   - [Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
3. **OAuth consent screen** → tipo *External* → adicione o email de quem vai usar como **Test user** (modo teste)
4. **Credentials** → *Create credentials* → *OAuth client ID* → tipo **Desktop app**
5. Copie **Client ID** e **Client Secret** para o `.env`:

```env
GOOGLE_ENABLED=true
GOOGLE_CLIENT_ID=123456789-xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
```

**Alternativa:** baixe o JSON e salve como `data/google_credentials.json`.

> **Dica:** guarde uma cópia deste `.env` (sem chaves LLM) num pendrive — ao instalar para outra pessoa, só falta ela autorizar a conta dela no passo “Para quem vai usar”.

### 2. Subir a Thina e conectar

```powershell
.\start-docker.ps1
.\scripts\setup_google.ps1
```

Os volumes Google já estão no `docker-compose.yml` — não é preciso editar o compose.

---

## O que você pode pedir por voz

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

## Avançado

### Reautorizar (permissões novas)

Na página http://localhost:8080/v1/google/setup → **Reconectar outra conta** (ou apague `data/google_token.json` e conecte de novo).

### URI de callback personalizada

Se a Thina não usar a porta 8080:

```env
GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8081/v1/google/oauth/callback
```

## Segurança

- `data/google_credentials.json` e `data/google_token.json` **não** vão para o Git.
- A Thina confirma antes de enviar email ou criar evento se o pedido for ambíguo.
- Revogue o acesso em [Conta Google → Segurança → Acesso de terceiros](https://myaccount.google.com/permissions) se necessário.
