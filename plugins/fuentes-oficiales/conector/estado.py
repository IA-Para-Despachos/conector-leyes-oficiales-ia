# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""Qué fuentes responden ahora: una petición ligera a cada una, a la vez (un hilo por fuente) y con plazo corto."""
from __future__ import annotations

import threading
import time

import perfil
from boe import API, WEB
from otras import BDNS, CATASTRO
from red import FuenteError, Sesion

PLAZO = 8  # segundos por fuente
LENTA = 3  # a partir de aquí, 'lenta'
# Fuente -> (URL, parámetros). Lo más ligero de cada una: una página de formulario o una consulta mínima.
COMPROBACIONES = {
    "BOE": (f"{API}/legislacion-consolidada/id/BOE-A-1978-31229/metadatos", None),
    "BORME": (f"{API}/borme/sumario/20260102", None),
    "Catastro": (f"{CATASTRO}/ObtenerProvincias", None),
    "VIES": ("https://ec.europa.eu/taxation_customs/vies/rest-api/check-status", None),
    "BDNS": (f"{BDNS}/convocatorias/busqueda", {"page": 0, "pageSize": 1}),
    "CELLAR (UE)": ("https://publications.europa.eu/webapi/rdf/sparql",
                    {"query": "ASK {}", "format": "application/sparql-results+json"}),
}
if not perfil.LIGHT:  # lo de la doctrina y los convenios solo va en el premium
    from convenios import REGCON
    from hacienda import DGT, TEAC
    from tc import TC
    COMPROBACIONES |= {
        "DGT": (f"{DGT}/", None),
        "TEAC": (f"{TEAC}/Criterios.aspx", None),
        "TC": (f"{TC}/es/Busqueda", None),
        "REGCON": (f"{REGCON}/consultaPublica", None),
        "Fiscalía (BOE)": (f"{WEB}/buscar/fiscalia.php", None),
    }


def _comprobar(nombre: str, salida: dict) -> None:
    url, params = COMPROBACIONES[nombre]
    inicio = time.monotonic()
    try:
        # La API del BOE exige que se pida JSON (si no, 400); a las webs no les estorba.
        cuerpo = Sesion().texto(url, params, timeout=PLAZO,
                                cabeceras={"Accept": "application/json, text/html;q=0.9, */*;q=0.8"})
        segundos = round(time.monotonic() - inicio, 1)
        if len(cuerpo) < 20:
            salida[nombre] = {"estado": "caída", "segundos": segundos, "motivo": "respondió vacío"}
        else:
            salida[nombre] = {"estado": "ok" if segundos < LENTA else "lenta", "segundos": segundos}
    except FuenteError as e:
        salida[nombre] = {"estado": "caída", "segundos": round(time.monotonic() - inicio, 1), "motivo": str(e)[:150]}
    except Exception as e:  # noqa: BLE001  (un fallo inesperado de una fuente no tumba la comprobación de las demás)
        salida[nombre] = {"estado": "caída", "motivo": f"error inesperado ({type(e).__name__})"}


def estado() -> dict:
    salida: dict = {}
    hilos = [threading.Thread(target=_comprobar, args=(n, salida), daemon=True) for n in COMPROBACIONES]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(PLAZO + 4)
    fuentes = [{"fuente": n, **salida.get(n, {"estado": "caída", "motivo": f"sin respuesta en {PLAZO} s"})}
               for n in COMPROBACIONES]
    caidas = [f["fuente"] for f in fuentes if f["estado"] == "caída"]
    return {"responden": f"{len(fuentes) - len(caidas)} de {len(fuentes)}", "fuentes": fuentes,
            "criterio": f"ok: menos de {LENTA} s; lenta: responde, pero tarda; caída: error o más de {PLAZO} s.",
            **({"aviso": f"Sin respuesta ahora: {', '.join(caidas)}. No uses esas herramientas hasta que vuelvan; "
                         "lo que digan, cítalo como 'no se pudo comprobar', nunca como 'no consta'."} if caidas else {}),
            "nota": "Una petición mínima por fuente: dice si la web responde, no si su buscador da resultados."}
