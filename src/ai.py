"""Cliente Claude compartilhado (visão e geração), com saída estruturada via pydantic."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Protocol, TypeVar

from PIL import Image
from pydantic import BaseModel

from .logging_setup import get_logger

log = get_logger("ai")
T = TypeVar("T", bound=BaseModel)

MAX_SIDE = 1568  # lado máximo recomendado para imagens enviadas ao modelo


class AIError(RuntimeError):
    pass


class StructuredLLM(Protocol):
    def generate(self, *, system: str, content: list[dict[str, Any]], schema: type[T],
                 max_tokens: int = 16000) -> T: ...


def image_block(path: Path) -> dict[str, Any]:
    """Converte imagem em bloco base64 JPEG redimensionado (economiza tokens)."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


class ClaudeLLM:
    """Wrapper fino sobre o SDK oficial `anthropic`.

    - Saída estruturada com `messages.parse(output_format=Modelo)`.
    - Fallback no servidor em caso de recusa (`fallbacks="default"`), opt-in via beta.
    - System prompt estável com cache (`cache_control`) para baratear chamadas repetidas.
    """

    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, api_key: str | None, model: str, effort: str = "medium", client: Any = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort

    def generate(self, *, system: str, content: list[dict[str, Any]], schema: type[T],
                 max_tokens: int = 16000) -> T:
        import anthropic

        try:
            resp = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_config={"effort": self.effort},
                output_format=schema,
            )
        except anthropic.RateLimitError as exc:
            raise AIError("limite de uso da API do Claude atingido; tente novamente mais tarde") from exc
        except anthropic.AuthenticationError as exc:
            raise AIError("ANTHROPIC_API_KEY inválida") from exc
        except anthropic.BadRequestError as exc:
            raise AIError(f"requisição inválida para o Claude: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"erro da API do Claude ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("sem conexão com a API do Claude") from exc

        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise AIError(f"o modelo recusou a solicitação (categoria: {cat})")
        if resp.stop_reason == "max_tokens":
            raise AIError("resposta truncada (max_tokens)")
        parsed = resp.parsed_output
        if parsed is None:
            raise AIError("resposta sem JSON válido")
        log.info("claude ok", extra={"data": {"modelo": resp.model, "schema": schema.__name__,
                                              "in": resp.usage.input_tokens, "out": resp.usage.output_tokens}})
        return parsed
