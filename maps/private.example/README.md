# Contexto privado da Thina

Copie esta pasta para `maps/private` (nao versionada):

```powershell
Copy-Item -Recurse maps\private.example maps\private
```

Edite os `.md` em `maps/private/`. Todos sao lidos em toda conversa.

| Arquivo | Uso |
|---------|-----|
| `user.md` | Voce: nome, familia, preferencias pessoais |
| `casa.md` | Casa: apelidos de comodos, luzes, entidades HA |
| `rotina.md` | Horarios, habitos, frases que costuma usar |
| `pc.md` | PC: apps, sites, atalhos de voz |
| `notas.md` | Qualquer outro contexto fixo |

O arquivo legado `maps/thina_user.private.md` ainda funciona; evite duplicar o mesmo conteudo em `user.md`.
