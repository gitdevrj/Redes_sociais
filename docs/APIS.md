# APIs — o que foi confirmado na documentação oficial

**Data da consulta:** 14/11/2026. As APIs mudam com frequência: antes de cada fase, as páginas abaixo são consultadas de novo e este arquivo é atualizado.

Legenda: ✅ confirmado na doc · ⚠️ ponto de atenção · 🔜 será detalhado na fase indicada

---

## Telegram Bot API — versão 10.4 (09/11/2026)
Fonte: https://core.telegram.org/bots/api

- ✅ `getUpdates` (long polling) e webhooks são mutuamente exclusivos. Usamos long polling, que dispensa expor o PC à internet.
- ✅ `getFile`: **o bot só baixa arquivos de até 20 MB** pelos servidores do Telegram.
- ✅ **Local Bot API Server** (`telegram-bot-api`): baixa arquivos **sem limite de tamanho**, envia até 2000 MB e devolve o caminho local no `file_path`. Exige `api_id`/`api_hash` de my.telegram.org.
- ✅ `callback_data` dos botões: 1–64 bytes. Os IDs do AutoPost têm cerca de 22 caracteres.
- ✅ `media_group_id` identifica fotos/vídeos enviados como álbum, usado para montar o carrossel.
- ⚠️ Foto enviada como "foto" é comprimida pelo Telegram. Para manter a qualidade, envie como **arquivo** (documento).

## Instagram — Instagram API with Facebook Login (Graph API v27.0 nos exemplos)
Fontes:
https://developers.facebook.com/docs/instagram-platform/content-publishing ·
https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media ·
https://developers.facebook.com/documentation/instagram-platform/content-publishing/audio-api (atualizada em 16/06/2026)

**Tipo de login escolhido: Facebook Login for Business.** É o único que libera upload resumível de vídeo local, rótulo de parceria paga e a Audio API.

- ✅ Permissões: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`. Para parceria paga: `instagram_branded_content_creator`.
- ✅ Fluxo em 2 passos: `POST /<IG_ID>/media` cria o contêiner, `GET /<container>?fields=status_code` acompanha o processamento e `POST /<IG_ID>/media_publish` publica.
- ✅ **Imagem: só JPEG**, sem MPO nem JPS, via `image_url` hospedada em **servidor público**, porque a Meta baixa a URL. Daí a necessidade do Google Drive na Fase 3.
- ✅ **Vídeo/Reels: upload resumível** (`upload_type=resumable` + `POST https://rupload.facebook.com/ig-api-upload/<container>`) aceita **arquivo local do computador**, sem precisar de URL pública.
- ✅ Legenda: **até 2200 caracteres, 30 hashtags e 20 @**. Não vale para itens dentro de carrossel.
- ✅ `collaborators`: até 3 usernames (feed, Reels e carrossel; não vale para Stories).
- ✅ `user_tags`, `location_id`, `cover_url`, `thumb_offset`, `share_to_feed`, `audio_name`.
- ✅ `alt_text`: só para **posts de imagem**. Reels e Stories não aceitam.
- ✅ `is_ai_generated`: autodeclaração de uso de IA. Não vale para itens de carrossel.
- ✅ Parceria paga: `is_paid_partnership=true` e/ou `branded_content_sponsor_ids` (até 2 marcas, exige Facebook Login).
- ✅ Carrossel: até **20** itens. O corte segue a 1ª imagem (padrão 1:1).
- ⚠️ Limite de publicação: a doc diz **100 posts por 24 h** no geral e **50** na seção de carrossel. O AutoPost usa **50** (`platforms.yaml`) e consulta `GET /<IG_ID>/content_publishing_limit` antes de publicar.

### 🎵 Instagram Audio API (mudou a regra 3 do projeto)
- ✅ `GET /ig_audio?audio_type=music|original_sound&user_id=...&search_query=...` busca músicas e áudios originais **autorizados para uso por terceiros**. Sem `search_query`, devolve os **áudios em alta**.
- ✅ Na criação do contêiner de Reels: `audio_configuration={"audio_id": "...", "audio_volume": 1-100, "video_volume": 1-100}`.
- ✅ Disponível na Instagram API with Facebook Login e na Unified Login. Não funciona na Instagram Login.
- ⚠️ Não há pré-visualização do Reel com o áudio anexado: ele é publicado como foi configurado. O painel vai mostrar o `download_url` (prévia temporária, cerca de 1,5 dia) para você ouvir antes.
- ⚠️ `is_ads_eligible` indica se o áudio pode ir para anúncio. Se o post for impulsionado, use só faixas com `true`.
- **Impacto:** no Instagram, a Fase 2 terá uma **estratégia C**, que é escolher a música na biblioteca do próprio Instagram via API, além de A (trilha licenciada embutida via FFmpeg) e B (rascunho com sugestão de áudio em alta). Essa trilha da biblioteca da Meta vale **só no Instagram**: nas outras redes o vídeo vai sem ela ou com trilha licenciada própria.

## Facebook (Páginas)
- 🔜 Fase 3: confirmar os endpoints de foto, álbum, vídeo e Reels de Página, além de permissões (`pages_manage_posts`, `pages_read_engagement`) e limites.

## LinkedIn — Posts API (perfil pessoal)
Fontes:
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api (atualizada em 13/05/2026) ·
https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin ·
https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format

- ✅ Postar como pessoa: escopo **`w_member_social`**. O autor é `urn:li:person:<id>`, obtido via Sign In with OpenID Connect.
- ✅ Endpoint `POST https://api.linkedin.com/rest/posts` com cabeçalho `Linkedin-Version: AAAAMM`.
- ⚠️ A versão **202511 será desativada em 16/11/2026**. Usar uma versão atual, a ser confirmada na Fase 3.
- ✅ O texto (`commentary`) usa o formato **little text**:
  - caracteres reservados precisam de escape (feito por `captions.escape_linkedin`);
  - menção: `@[Nome](urn:li:person:123)`;
  - hashtag: `#tag`.
- ⚠️ `r_member_social`, que lê posts e métricas do perfil pessoal, é **restrita** e só sai para apps aprovados. Isso afeta a **Fase 4 (métricas)** no LinkedIn pessoal.
- 🔜 Fase 3: upload de imagem e vídeo pelas Images/Videos API.

## YouTube Data API v3 — `videos.insert`
Fonte: https://developers.google.com/youtube/v3/docs/videos/insert (atualizada em 12/11/2026)

- ✅ Escopo mínimo: `https://www.googleapis.com/auth/youtube.upload`.
- ✅ Arquivo de até 256 GB, `video/*`.
- ✅ **Cota: 100 chamadas/dia** de upload. Cada chamada custa 1 unidade no balde "Video Uploads".
- ✅ Campos aceitos:
  - `snippet.title`, `snippet.description`, `snippet.tags[]`, `snippet.categoryId`, `snippet.defaultLanguage`;
  - `status.privacyStatus`, `status.publishAt` (agendamento nativo), `status.selfDeclaredMadeForKids`, `status.containsSyntheticMedia`.
- ✅ `privacyStatus` sem valor vira **público**. O AutoPost sempre envia o valor explicitamente (padrão `private`, em `platforms.yaml`).
- ✅ Vídeos enviados por projetos de API **não verificados não ficam mais restritos ao modo privado**, segundo a doc atual.
- 🔜 Fase 3: confirmar os limites de título e descrição no recurso `videos` e as regras de Shorts.

## TikTok — Content Posting API
- Desativado em `platforms.yaml`. 🔜 Será consultado quando você ativar o TikTok.

## Claude (Anthropic) — análise e redação
- ✅ SDK oficial `anthropic` 2.8. Saída estruturada com `client.beta.messages.parse(output_format=<Modelo pydantic>)`.
- ✅ `fallbacks="default"` (beta `server-side-fallback-2026-07-01`): se o modelo recusar, o servidor tenta outro automaticamente.
- ✅ O system prompt da marca vai com `cache_control` para reduzir custo nas chamadas repetidas.
- Modelo configurável em `.env` (`CLAUDE_MODEL`, padrão `claude-sonnet-5-5`) e esforço em `CLAUDE_EFFORT` (padrão `medium`).
