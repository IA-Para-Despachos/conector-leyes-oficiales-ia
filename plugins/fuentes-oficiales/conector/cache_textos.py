# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Caché en disco del texto ya extraído (nunca el PDF), en datos/textos/ (fuera de git). Decidido por Jurium (ronda 19):
la segunda lectura de un convenio es instantánea y una sentencia guardada se puede leer después de borrar su PDF.

Escritura acotada: la carpeta es fija (no viene de fuera), el nombre de cada archivo es un hash de la clave, no se
siguen enlaces (la carpeta y el archivo no pueden ser simbólicos ni junctions) y se escribe en un temporal que se
renombra (nunca queda un archivo a medias). Cada archivo: una línea de cabecera (clave y nombre para listar) y otra con
los datos. Un archivo que no tenga esa forma se ignora (y se borra): se vuelve a leer de la fuente."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import rutas

RAIZ = rutas.ruta("datos") / "textos"
# Convenios: lo más antiguo se borra solo al pasar del tope (se vuelve a descargar si hace falta). Sentencias: no se
# borran solas (el PDF puede no existir ya); si se llena, deja de guardar y lo avisa.
TOPES = {"convenios": 150_000_000, "sentencias": 300_000_000}
MAX_ARCHIVO = 30_000_000
_NOMBRE = re.compile(r"[0-9a-f]{64}\.jsonl")


def _carpeta(espacio: str) -> Path | None:
    """La carpeta del espacio, creada si hace falta; None si no es una carpeta normal dentro de datos/ (enlace o junction)."""
    if espacio not in TOPES:
        raise ValueError("espacio de caché desconocido")
    carpeta = RAIZ / espacio
    if not _normal(RAIZ.parent):  # datos/ (la del índice del BORME), antes de crear nada dentro
        return None
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta if all(map(_normal, (RAIZ, carpeta))) and carpeta.resolve() == carpeta else None


def _normal(p: Path) -> bool:
    """Una carpeta de verdad: ni enlace simbólico ni junction (Python 3.11 no tiene is_junction: lo cubre resolve())."""
    return p.is_dir() and not p.is_symlink() and not getattr(p, "is_junction", lambda: False)()


def _ruta(carpeta: Path, clave: str) -> Path:
    return carpeta / f"{hashlib.sha256(clave.encode('utf-8', 'replace')).hexdigest()}.jsonl"


def leer(espacio: str, clave: str) -> dict | None:
    """Los datos guardados con esa clave, o None (no hay, o el archivo no tiene la forma esperada)."""
    try:
        carpeta = _carpeta(espacio)
        if carpeta is None:
            return None
        ruta = _ruta(carpeta, clave)
        if ruta.is_symlink() or not ruta.is_file() or ruta.stat().st_size > MAX_ARCHIVO:
            return None
        with open(ruta, encoding="utf-8") as f:
            cabecera, datos = json.loads(f.readline(10_000)), json.loads(f.read(MAX_ARCHIVO))
        if not (isinstance(cabecera, dict) and cabecera.get("clave") == clave and isinstance(datos, dict)):
            ruta.unlink(missing_ok=True)
            return None
        os.utime(ruta)  # usado ahora: es lo último que se borra
        return datos
    except (OSError, ValueError, RecursionError):
        return None


def guardar(espacio: str, clave: str, datos: dict, nombre: str = "") -> bool:
    """Guarda los datos (JSON); False si no se pudo o no cabe. Nunca hace fallar la herramienta que llama."""
    try:
        carpeta = _carpeta(espacio)
        if carpeta is None:
            return False
        linea = json.dumps({"clave": clave, "nombre": nombre[:200]}, ensure_ascii=False)
        cuerpo = json.dumps(datos, ensure_ascii=False)
        if len(cuerpo) > MAX_ARCHIVO or not _hacer_sitio(espacio, carpeta, len(cuerpo.encode("utf-8"))):
            return False
        ruta = _ruta(carpeta, clave)
        temporal = carpeta / f"{ruta.stem}.{os.getpid()}.tmp"
        with open(temporal, "x", encoding="utf-8") as f:  # 'x': nunca abre algo que ya exista (ni un enlace)
            f.write(linea + "\n" + cuerpo)
        os.replace(temporal, ruta)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _archivos(carpeta: Path) -> list[Path]:
    return [p for p in carpeta.iterdir() if _NOMBRE.fullmatch(p.name) and not p.is_symlink() and p.is_file()]


def _hacer_sitio(espacio: str, carpeta: Path, nuevo: int) -> bool:
    """Convenios: borra los más antiguos hasta que quepa. Sentencias: solo dice si cabe."""
    archivos = sorted(_archivos(carpeta), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in archivos)
    if espacio != "convenios":
        return total + nuevo <= TOPES[espacio]
    while archivos and total + nuevo > TOPES[espacio]:
        viejo = archivos.pop(0)
        total -= viejo.stat().st_size
        viejo.unlink(missing_ok=True)
    return total + nuevo <= TOPES[espacio]


def nombres(espacio: str) -> list[str]:
    """Los nombres guardados en la cabecera de cada archivo (lo más reciente primero), sin leer los datos."""
    try:
        carpeta = _carpeta(espacio)
        if carpeta is None:
            return []
        salida = []
        for p in sorted(_archivos(carpeta), key=lambda p: p.stat().st_mtime, reverse=True)[:500]:
            with open(p, encoding="utf-8") as f:
                cabecera = json.loads(f.readline(10_000) or "{}")
            if isinstance(cabecera, dict) and isinstance(cabecera.get("nombre"), str) and cabecera["nombre"]:
                salida.append(cabecera["nombre"])
        return salida
    except (OSError, ValueError, RecursionError):
        return []


def borrar(espacio: str, clave: str) -> bool:
    """Quita el texto guardado con esa clave (quitar una sentencia de la base propia)."""
    try:
        carpeta = _carpeta(espacio)
        if carpeta is None:
            return False
        _ruta(carpeta, clave).unlink(missing_ok=True)
        return True
    except (OSError, ValueError):
        return False
