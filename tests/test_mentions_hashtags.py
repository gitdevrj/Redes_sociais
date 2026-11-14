from src.config import Perfil
from src.generator.hashtags import build_hashtags, normalize
from src.generator.mentions import resolve_mentions

from .conftest import analysis


def _add_partner(cfg, **kw):
    data = dict(id="contec", nome="Contec Contabilidade", tipo="parceiro",
                handles={"instagram": "@contec", "facebook": "@contecfb", "linkedin": "urn:li:organization:1"},
                palavras_chave=["contec"], logos=["Contec"], auto_marcar=True, colaborador_instagram=True)
    data.update(kw)
    cfg.mentions.perfis.append(Perfil(**data))


def test_never_invents_handles(cfg):
    a = analysis(briefing="Gravado com @fulano_desconhecido", logos_marcas=["Banco X"])
    marc, sug, colab = resolve_mentions("instagram", a, cfg)
    assert marc == [] and colab == []
    handles = {m.handle for m in sug}
    assert "@fulano_desconhecido" in handles
    assert any(m.nome == "Banco X" and m.handle == "" for m in sug)


def test_registered_partner_is_tagged_from_keyword_and_logo(cfg):
    _add_partner(cfg)
    a = analysis(briefing="Evento com a Contec")
    marc, _, colab = resolve_mentions("instagram", a, cfg)
    assert [m.handle for m in marc] == ["@contec"] and colab == ["contec"]
    marc_li, _, _ = resolve_mentions("linkedin", a, cfg)
    assert marc_li[0].handle == "urn:li:organization:1"

    a2 = analysis(logos_marcas=["Contec"])
    marc2, _, _ = resolve_mentions("facebook", a2, cfg)
    assert marc2[0].origem == "logo"


def test_partner_without_auto_tag_is_only_suggested(cfg):
    _add_partner(cfg, auto_marcar=False)
    marc, sug, _ = resolve_mentions("instagram", analysis(briefing="contec"), cfg)
    assert marc == [] and sug[0].handle == "@contec"


def test_hashtag_normalization_and_limits(cfg):
    assert normalize("#Finanças Pessoais!") == "#financaspessoais"
    assert normalize("123") == ""
    ig = build_hashtags("instagram", cfg, "indicadores", ["dashboards_bi"], ["#EBITDA", "#gestão"])
    assert 3 <= len(ig) <= 8 and ig[0] == "#robertojuniorup"
    assert len(ig) == len(set(ig))
    assert len(build_hashtags("facebook", cfg, "indicadores", [], ["#x"])) <= 3
    assert len(build_hashtags("youtube", cfg, "indicadores", [], [])) == 3
