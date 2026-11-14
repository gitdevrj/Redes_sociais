# AutoPost — publicador automático de conteúdo

Você envia um vídeo ou uma imagem (pela pasta `inbox/` ou pelo **Telegram**). O AutoPost entende o conteúdo e gera, para cada rede, legenda (3 variações), hashtags, marcações autorizadas, texto alternativo, título (YouTube) e horário sugerido. Depois coloca tudo numa **fila de aprovação**, que você revisa pelo painel web ou pelo próprio Telegram.

Redes ativas: **Instagram, Facebook, LinkedIn (perfil pessoal) e YouTube**. O TikTok está preparado, mas desligado.

| Fase | Conteúdo | Status |
|---|---|---|
| 1 | Ingestão (pasta + Telegram), análise (FFmpeg, PySceneDetect, Whisper, Claude Vision), legendas/hashtags/marcações, painel de aprovação | ✅ pronta |
| 2 | Música licenciada + mixagem, reenquadramento 9:16/1:1/4:5/16:9, legendas queimadas, capa | 🔜 |
| 3 | Publicação e agendamento (Instagram/Facebook → LinkedIn → YouTube) | 🔜 |
| 4 | Métricas e aprendizado de horários/hashtags | 🔜 |

> **Segurança:** por padrão `DRY_RUN=true` e `auto_publish: false`. Nada é publicado sem a sua aprovação.

---

## 1. Instalação no Windows

1. **Python 3.11 ou superior.** Baixe em https://www.python.org/downloads/ e marque *Add Python to PATH* na instalação.
2. **FFmpeg.** No PowerShell:
   ```powershell
   winget install --id Gyan.FFmpeg -e
   ```
   Feche e abra o terminal de novo. Depois confirme com `ffmpeg -version`.
3. **Projeto.** No PowerShell, dentro da pasta do projeto:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   copy .env.example .env
   notepad .env
   ```
   Se o PowerShell bloquear o `Activate.ps1`, rode antes: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
4. **Transcrição (Whisper local).** Na primeira execução, o `faster-whisper` baixa o modelo (cerca de 460 MB no `small`). Em CPU comum, um vídeo de 1 minuto leva cerca de 20–60 s. Se o PC for mais fraco, use `WHISPER_MODEL=base` no `.env`.

### Alternativa: Docker Desktop
```powershell
docker compose up -d --build
```
Sobem 3 serviços: `watcher` (pasta inbox), `bot` (Telegram) e `panel` (painel em http://localhost:8000). No Docker do Windows, o watcher usa *polling* (`WATCHER_POLLING=true`), porque eventos de arquivo não atravessam para o container.

---

## 2. Configuração

| Arquivo | Para quê |
|---|---|
| `.env` | Chaves, tokens e senha do painel. **Nunca versione.** |
| `config/brand.yaml` | Nome, pilares (Clareza, Direção, Lucro, Segurança), temas, tom de voz, palavras proibidas, CTA, hashtags da marca, cores |
| `config/mentions.yaml` | **Única fonte de @.** Parceiros, clientes autorizados e colaboradores, com palavras-chave, logos e consentimento (LGPD) |
| `config/platforms.yaml` | Redes ativas, formatos, limites (confirmados em `docs/APIS.md`) e locais conhecidos |
| `config/schedule.yaml` | Janelas de postagem por rede e dia, espaçamento entre redes, modo automático |
| `music/catalog.yaml` | Biblioteca de músicas licenciadas (Fase 2) |

Pontos de atenção na configuração:

- **Temas de investimentos e consórcios** recebem automaticamente um aviso de "conteúdo educativo".
- **Física quântica** tem uma diretriz para ser usada como **metáfora**, sem afirmações científicas indevidas. Ajuste em `brand.yaml` se quiser.
- **Parceria paga:** escreva `#publi` ou "parceria paga" no briefing. O post é marcado como `is_sponsored` e recebe o aviso.

### IA (Claude)
Coloque `ANTHROPIC_API_KEY` no `.env`. Sem a chave, o sistema roda em **modo offline**: gera textos-modelo, a nota de confiança fica limitada a 40 e **todo post exige revisão**. O modelo é configurável em `CLAUDE_MODEL` (padrão `claude-sonnet-5-5`).

### Telegram (envio de mídia e aprovação)
1. No Telegram, fale com o **@BotFather**, envie `/newbot` e copie o token para `TELEGRAM_BOT_TOKEN`.
2. Rode `python -m src.main bot`, abra o seu bot e envie `/meuid`.
3. Copie o número para `TELEGRAM_ALLOWED_USER_IDS` e `TELEGRAM_NOTIFY_CHAT_ID` e reinicie o bot.

Como usar:
- Envie o vídeo ou a foto **como arquivo** (📎 → Arquivo) para não perder qualidade. O texto que você escrever junto vira o briefing.
- Um **álbum** com várias fotos vira um **carrossel**.
- Quando o post fica pronto, chega a prévia com os botões **Aprovar / Regenerar / Descartar**.
- Comandos: `/status`, `/regen <id> mais curto, foco em MEI`, `/aprovar <id>` e `/descartar <id>`.
- ⚠️ **Limite de 20 MB:** é o máximo que um bot consegue baixar pelos servidores do Telegram. Para arquivos maiores, você tem duas saídas:
  - (a) jogar o arquivo na pasta `inbox/`, que pode ser uma pasta do Google Drive para computador; nesse caso use `WATCHER_POLLING=true`;
  - (b) ativar o **Local Bot API Server**: crie `api_id`/`api_hash` em https://my.telegram.org, preencha `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`, rode `docker compose --profile telegram-local up -d` e defina `TELEGRAM_API_BASE=http://telegram-bot-api:8081`. Antes, chame `logOut` no bot uma vez, conforme a documentação do Telegram.

---

## 3. Como usar

```powershell
python -m src.main run            # tudo junto: pasta inbox + bot do Telegram + painel
python -m src.main review         # só o painel → http://127.0.0.1:8000
python -m src.main analyze examples\dashboard_margem.jpg   # processa um arquivo e imprime o JSON
python -m src.main status         # fila
```

Formas de enviar conteúdo:

- **Pasta `inbox/`:**
  - um arquivo solto vira um post;
  - uma **subpasta** com várias imagens vira um **carrossel**;
  - um `arquivo.txt` com o mesmo nome do arquivo é o **briefing**, que tem prioridade sobre a análise automática.
- Formatos aceitos: `.mp4 .mov .m4v .jpg .jpeg .png .heic .webp`. O HEIC é convertido para JPG.
- Resultado de cada post:
  - `output/<id>/analysis.json` traz a análise;
  - `output/<id>/<rede>.json` traz o post de cada rede.

### Painel de aprovação
- Abra http://127.0.0.1:8000. Usuário e senha ficam em `REVIEW_USER`/`REVIEW_PASSWORD`. O painel roda só no seu PC.
- Para cada rede você vê:
  - a prévia da mídia;
  - as 3 legendas editáveis (marque a escolhida);
  - as hashtags e as marcações;
  - as sugestões de @, que **só viram marcação depois de cadastradas** em `mentions.yaml`;
  - o horário sugerido, os alertas e os riscos.
- Botões: **Salvar**, **Aprovar (agendar)**, **Aprovar e publicar agora**, **Reagendar**, **Regenerar** (com instrução livre) e **Descartar**.
- Posts com **riscos** (CPF/CNPJ visível, menores de idade, marca de terceiros…) são sempre de revisão obrigatória, mesmo no modo automático.

### Exemplos
```powershell
python scripts\make_samples.py    # cria examples\ (imagem, carrossel e vídeo vertical)
python -m src.main analyze examples\fluxo_de_caixa_erros.mp4
```

---

## 4. Apps de desenvolvedor (resumo; o passo a passo detalhado vem na Fase 3)

| Rede | Onde | Permissões/escopos | Observação |
|---|---|---|---|
| Instagram + Facebook | developers.facebook.com → app do tipo *Business* com **Facebook Login for Business** | `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`, `pages_manage_posts`; parceria paga: `instagram_branded_content_creator` | Conta Instagram profissional vinculada a uma Página. Esse login libera upload de vídeo local e a Audio API |
| LinkedIn (pessoal) | linkedin.com/developers → produto *Share on LinkedIn* + *Sign In with LinkedIn using OpenID Connect* | `w_member_social`, `openid`, `profile` | Métricas do perfil pessoal (`r_member_social`) são restritas |
| YouTube | console.cloud.google.com → ativar *YouTube Data API v3* → credencial OAuth do tipo *App para computador* | `youtube.upload` | Cota de 100 uploads/dia. Publica como `private` por padrão (`platforms.yaml`) |

Os tokens vão **só** no `.env`. A renovação automática de tokens entra na Fase 3.

## 5. Biblioteca de músicas (Fase 2)
Use apenas faixas com licença para uso comercial (YouTube Audio Library, Pixabay Music…). Coloque os arquivos em `music/` e descreva cada um em `music/catalog.yaml`, com licença, mood, BPM e duração.

No Instagram também será possível usar a **biblioteca de músicas do próprio Instagram via API** (Audio API), conforme `docs/APIS.md`.

## 6. Testes
```powershell
pytest
```
As APIs são simuladas (mocks) e nada sai do seu computador.

## 7. Estrutura
```
config/          YAMLs da marca, marcações, redes e horários
src/ingest.py    ingestão (IDs, HEIC→JPG, carrossel, briefing)
src/watcher.py   monitor da pasta inbox
src/telegram_bot.py  envio de mídia e aprovação pelo Telegram
src/analyzer/    video.py · audio.py · vision.py · content.py
src/generator/   captions.py · hashtags.py · mentions.py
src/review_queue/ db.py (SQLite) · review_app.py (painel) · actions.py
src/scheduler.py sugestão de horários · src/notifier.py notificações
src/publishers/  interface comum (implementações na Fase 3)
docs/APIS.md     o que foi confirmado em cada API e quando
```
A pasta da fila chama `review_queue/`, e não `queue/`, para não conflitar com o módulo `queue` do Python.
