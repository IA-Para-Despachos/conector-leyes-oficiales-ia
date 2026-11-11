# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Dónde viven los datos del conector: una sola función para todo lo que se escribe o se guarda.

- Como plugin de Claude Code (el reparto a los despachos): en la carpeta persistente que Claude Code da a cada plugin
  (variable CLAUDE_PLUGIN_DATA, ~/.claude/plugins/data/<plugin>/), que sobrevive a las actualizaciones: el código del
  plugin se sustituye entero y no se escribe nunca en él.
- En desarrollo (Claude Code abierto en la carpeta del conector): datos/, jurisprudencia/ y convenios/ junto a conector/,
  como siempre (fuera de git)."""
from __future__ import annotations

import os
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
NOMBRES = ("datos", "jurisprudencia", "convenios")


def ruta(nombre: str) -> Path:
    """'datos' (índice del BORME, copia de textos, base de sentencias, feedback, activación) o 'jurisprudencia' y
    'convenios' (los PDF que guarda el usuario)."""
    if nombre not in NOMBRES:
        raise ValueError(f"ruta desconocida: {nombre!r}")
    plugin = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if plugin and Path(plugin).is_absolute():
        base = Path(plugin).resolve()
        base.mkdir(parents=True, exist_ok=True)
        return base if nombre == "datos" else base / nombre
    return _RAIZ / nombre
