"""Sugestão de horários (Fase 1). A execução agendada das publicações entra na Fase 3 (APScheduler)."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Schedule

DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def _windows(sched: Schedule, rede: str, day: datetime) -> list[tuple[datetime, datetime]]:
    tz = day.tzinfo
    out = []
    for w in sched.janelas.get(rede, {}).get(DIAS[day.weekday()], []) or []:
        ini, fim = (time.fromisoformat(x.strip()) for x in w.split("-"))
        out.append((datetime.combine(day.date(), ini, tz), datetime.combine(day.date(), fim, tz)))
    return out


def suggest_times(redes: list[str], sched: Schedule, now: datetime | None = None,
                  ocupados: dict[str, list[datetime]] | None = None, horizon_days: int = 14) -> dict[str, datetime]:
    """Próximo horário livre por rede, dentro das janelas, com espaçamento entre redes e limite diário."""
    tz = ZoneInfo(sched.fuso_horario)
    now = (now or datetime.now(tz)).astimezone(tz)
    earliest = now + timedelta(minutes=sched.antecedencia_minima_min)
    gap = timedelta(minutes=sched.espacamento_entre_redes_min)
    max_dia = int(sched.frequencia.get("max_posts_por_dia_por_rede", 2))
    ocupados = {k: [d.astimezone(tz) for d in v] for k, v in (ocupados or {}).items()}
    escolhidos: list[datetime] = []
    result: dict[str, datetime] = {}

    for rede in redes:
        taken = ocupados.get(rede, [])
        found: datetime | None = None
        for d in range(horizon_days):
            day = (now + timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
            if sum(1 for t in taken if t.date() == day.date()) >= max_dia:
                continue
            for ini, fim in _windows(sched, rede, day):
                cand = max(ini, earliest)
                cand = cand.replace(second=0, microsecond=0)
                if cand.minute % 5:
                    cand += timedelta(minutes=5 - cand.minute % 5)
                while cand <= fim:
                    conflito = any(abs(cand - e) < gap for e in escolhidos + taken)
                    if not conflito:
                        found = cand
                        break
                    cand += timedelta(minutes=5)
                if found:
                    break
            if found:
                break
        if found:
            result[rede] = found
            escolhidos.append(found)
    return result
