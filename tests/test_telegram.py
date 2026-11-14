import io

from PIL import Image

from src.telegram_bot import TelegramBot


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (1, 2, 3)).save(buf, "JPEG")
    return buf.getvalue()


class FakeTG:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "getUpdates":
            u, self.updates = self.updates, []
            return u
        if method == "getFile":
            return {"file_path": f"photos/{params['file_id']}.jpg"}
        return {}

    def download(self, file_path):
        return _jpeg()

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]


def _bot(settings, db, ingested):
    tg = FakeTG()
    bot = TelegramBot(settings, db, on_ingested=lambda ids, chat: ingested.extend(ids), client=tg, group_wait=0)
    return bot, tg


def _photo_msg(mid, user=111, group=None, caption=None, size=1000):
    m = {"message_id": mid, "chat": {"id": user}, "from": {"id": user},
         "photo": [{"file_id": f"small{mid}", "file_size": 10}, {"file_id": f"f{mid}", "file_size": size}]}
    if group:
        m["media_group_id"] = group
    if caption:
        m["caption"] = caption
    return {"update_id": mid, "message": m}


def test_unauthorized_user_is_ignored(settings, db):
    ids: list[str] = []
    bot, tg = _bot(settings, db, ids)
    bot.handle_update(_photo_msg(1, user=999))
    assert ids == [] and any("não autorizado" in t for t in tg.texts())


def test_meuid_works_for_anyone(settings, db):
    bot, tg = _bot(settings, db, [])
    bot.handle_update({"update_id": 1, "message": {"message_id": 1, "chat": {"id": 5}, "from": {"id": 5}, "text": "/meuid"}})
    assert "5" in tg.texts()[0]


def test_single_photo_with_caption_becomes_post_with_briefing(settings, db):
    ids: list[str] = []
    bot, tg = _bot(settings, db, ids)
    bot.handle_update(_photo_msg(10, caption="Margem de contribuição para MEI"))
    assert len(ids) == 1
    post = db.get(ids[0])
    assert post.origem == "telegram" and post.briefing == "Margem de contribuição para MEI"
    assert post.telegram_chat_id == 111
    assert ("getFile", {"file_id": "f10"}) in tg.calls  # pegou a maior resolução


def test_album_becomes_carousel(settings, db):
    ids: list[str] = []
    bot, tg = _bot(settings, db, ids)
    tg.updates = [_photo_msg(20, group="G1", caption="3 indicadores"), _photo_msg(21, group="G1"),
                  _photo_msg(22, group="G1")]
    bot.poll_once(timeout=0)
    assert len(ids) == 1
    post = db.get(ids[0])
    assert post.tipo == "carousel" and len(post.arquivos) == 3 and post.briefing == "3 indicadores"


def test_large_file_is_refused_with_guidance(settings, db):
    ids: list[str] = []
    bot, tg = _bot(settings, db, ids)
    bot.handle_update(_photo_msg(30, size=25 * 1024 * 1024))
    assert ids == [] and any("20 MB" in t for t in tg.texts())


def test_callback_approve_and_regen_flow(settings, db):
    ids: list[str] = []
    regens: list[tuple] = []
    bot, tg = _bot(settings, db, ids)
    bot.on_regen = lambda pid, instr, chat: regens.append((pid, instr))
    bot.handle_update(_photo_msg(40))
    pid = ids[0]
    db.upsert_rede(pid, "instagram", status="gerado")
    db.update(pid, status="gerado")
    bot.handle_update({"update_id": 41, "callback_query": {"id": "cq", "from": {"id": 111},
                                                          "message": {"chat": {"id": 111}}, "data": f"rg:{pid}"}})
    bot.handle_update({"update_id": 42, "message": {"message_id": 42, "chat": {"id": 111}, "from": {"id": 111},
                                                    "text": "mais curto"}})
    assert regens == [(pid, "mais curto")]
    bot.handle_update({"update_id": 43, "callback_query": {"id": "cq2", "from": {"id": 111},
                                                          "message": {"chat": {"id": 111}}, "data": f"ap:{pid}"}})
    assert db.get(pid).status == "aprovado"
    assert any("DRY-RUN" in t for t in tg.texts())
