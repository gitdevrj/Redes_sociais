"""Gera mídias de exemplo em examples/ (imagem tipo dashboard, carrossel e vídeo vertical com 3 cenas)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples"
NAVY, GOLD, WHITE = (11, 37, 69), (242, 193, 78), (255, 255, 255)


def font(size: int) -> ImageFont.ImageFont:
    for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def dashboard(path: Path, titulo: str, valores: list[int], w: int = 1080, h: int = 1350) -> None:
    im = Image.new("RGB", (w, h), NAVY)
    d = ImageDraw.Draw(im)
    d.text((70, 80), titulo, font=font(64), fill=WHITE)
    d.text((70, 170), "Jan a Jun · valores em R$ mil", font=font(34), fill=GOLD)
    base, bw = h - 220, 110
    meses = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun"]
    for i, v in enumerate(valores):
        x = 90 + i * 160
        d.rectangle([x, base - v * 7, x + bw, base], fill=GOLD if i == len(valores) - 1 else (90, 130, 190))
        d.text((x + 10, base - v * 7 - 50), str(v), font=font(36), fill=WHITE)
        d.text((x + 20, base + 20), meses[i], font=font(32), fill=WHITE)
    d.text((70, h - 110), "Margem de contribuição", font=font(40), fill=WHITE)
    im.save(path, "JPEG", quality=92)


def slide(path: Path, texto: str, sub: str, cor=NAVY, w: int = 1080, h: int = 1920) -> None:
    im = Image.new("RGB", (w, h), cor)
    d = ImageDraw.Draw(im)
    d.text((80, h // 2 - 120), texto, font=font(84), fill=WHITE)
    d.text((80, h // 2 + 20), sub, font=font(44), fill=GOLD)
    im.save(path, "PNG")


def main() -> None:
    EX.mkdir(exist_ok=True)
    # 1) imagem única + briefing
    dashboard(EX / "dashboard_margem.jpg", "Margem subiu 38%", [32, 35, 31, 40, 42, 44])
    (EX / "dashboard_margem.txt").write_text(
        "Dashboard real (dados fictícios) mostrando a margem de contribuição de uma PME no 1º semestre. "
        "Quero explicar o que é margem de contribuição e por que ela importa mais que o faturamento.",
        encoding="utf-8")
    # 2) carrossel
    car = EX / "carrossel_indicadores"
    car.mkdir(exist_ok=True)
    for i, (t, v) in enumerate([("Ticket médio", [20, 22, 21, 25, 27, 30]), ("CAC", [50, 48, 45, 40, 38, 35]),
                                ("EBITDA", [10, 12, 15, 14, 18, 21])], start=1):
        dashboard(car / f"{i}_{t.replace(' ', '_').lower()}.jpg", t, v)
    (car / "briefing.txt").write_text("3 indicadores financeiros que todo empresário deveria acompanhar todo mês.",
                                      encoding="utf-8")
    # 3) vídeo vertical 9:16 com 3 cenas + tom de áudio
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        slide(t / "s1.png", "Fluxo de caixa", "3 erros que custam caro")
        slide(t / "s2.png", "Erro 1", "Misturar conta PF e PJ", cor=(19, 49, 92))
        slide(t / "s3.png", "Erro 2", "Não prever o capital de giro", cor=(40, 30, 80))
        lst = t / "list.txt"
        lst.write_text("".join(f"file '{p}'\nduration 4\n" for p in ("s1.png", "s2.png", "s3.png")) + "file 's3.png'\n")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-f", "lavfi", "-i", "sine=frequency=220:duration=12", "-shortest",
                        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-c:a", "aac", "-b:a", "128k",
                        str(EX / "fluxo_de_caixa_erros.mp4")], check=True, cwd=t)
    (EX / "fluxo_de_caixa_erros.txt").write_text(
        "Reels sobre fluxo de caixa: os erros mais comuns de quem tem PME — misturar conta pessoa física e "
        "jurídica e não prever o capital de giro. Público: donos de pequenas empresas.", encoding="utf-8")
    print("Exemplos gerados em", EX)


if __name__ == "__main__":
    main()
