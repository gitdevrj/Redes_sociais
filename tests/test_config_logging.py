from src.logging_setup import redact


def test_configs_load(cfg):
    assert set(cfg.platforms.ativas()) == {"instagram", "facebook", "linkedin", "youtube"}
    assert cfg.brand.pilares == ["Clareza", "Direção", "Lucro", "Segurança"]
    assert cfg.platforms.redes["instagram"].legenda_max_caracteres == 2200
    assert cfg.schedule.modo.auto_publish is False
    assert "investimentos" in cfg.brand.temas and cfg.brand.temas["investimentos"].disclaimer


def test_redact_secrets_and_personal_data():
    s = ("GET https://api.telegram.org/bot123456:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789/getFile "
         "access_token=EAAB123 Bearer xyz.abc sk-ant-api03-SECRET cpf 123.456.789-09 cnpj 12.345.678/0001-90")
    out = redact(s)
    for leaked in ("ABCdef", "EAAB123", "xyz.abc", "SECRET", "123.456.789-09", "12.345.678/0001-90"):
        assert leaked not in out
