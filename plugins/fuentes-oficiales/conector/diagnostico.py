# Fuentes oficiales (versión abierta) 0.3.1. Hecho por Jurium. Licencia MIT (LICENSE).
"""diagnostico: el chequeo de la instalación, en lenguaje llano, y el canario por fuente.

Solo corre cuando se llama (nunca al arrancar la sesión). Dice qué está bien, qué falla y cuál es el siguiente paso.
El canario es una consulta estable por fuente con una marca esperada en el resultado (p. ej. el art. 1 del Código Civil
contiene 'ordenamiento jurídico'): separa 'la web no responde' (red, o caída: no es culpa del conector) de 'responde,
pero ya no con la forma que el conector entiende' (la web ha cambiado y el conector necesita arreglo)."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import estado as _estado
import perfil
import rutas
from red import MARCA, VERSION, FuenteError

RAIZ = Path(__file__).resolve().parent.parent
PLAZO_CANARIO = 45  # segundos como mucho por canario (REGCON y la DGT son lentas)
SKILLS = {"light": ("ordenanzas-municipales", "fuentes-ayuda", "jurium-recursos"),
          "premium": ("jurisprudencia-cendoj", "convenios-boletines", "ordenanzas-municipales", "escrito-con-fuentes",
                      "feedback", "fuentes-ayuda")}
_BASICAS = {"estado", "diagnostico", "articulo_vigente", "verificar_escrito"}
_FAQ = "FAQ.md, en la carpeta del plugin"


def canarios() -> dict:
    """{fuente: (consulta, marca esperada)}. Los nombres son los de estado.COMPROBACIONES. Solo se importa lo del perfil."""
    import boe
    import normas_ue
    import otras
    c = {
        "BOE": (lambda: boe.articulo("CC", "1", 3000), "ordenamiento jurídico"),
        "BORME": (lambda: boe.sumario_borme("2026-01-02"), "alicante"),
        "CELLAR (UE)": (lambda: normas_ue.articulo_ue("RGPD", "1", 3000), "personas físicas"),
        "Catastro": (lambda: otras.buscar_catastro_por_direccion("MADRID", "MADRID", "ALCALA", "1"), "referencia_catastral"),
        "VIES": (lambda: otras.validar_nif_iva("ESA28015865"), '"valido": true'),
        "BDNS": (lambda: "ok" if otras.buscar_subvenciones(None, None, None, 1)["total"] > 0 else "", "ok"),
    }
    if not perfil.LIGHT:
        import convenios
        import fiscalia
        import hacienda
        import tc
        c |= {
            "DGT": (lambda: hacienda.leer_consulta_dgt("V0648-24", 500), "ley 35/2006"),
            "TEAC": (lambda: hacienda.leer_criterio_teac("00/04214/2024", 500), "00/04214/2024"),
            "TC": (lambda: tc.buscar_tc(numero="137/2025"), "137/2025"),
            "REGCON": (lambda: convenios.buscar_convenio("hostelería", "estatal", "sector", "", 3), "hosteler"),
            "Fiscalía (BOE)": (lambda: fiscalia.leer_doctrina_fiscalia("Circular 1/2016", "", 500), "circular 1/2016"),
        }
    return c


def _canario(nombre: str, consulta, marca: str, salida: dict) -> None:
    inicio = time.monotonic()
    try:
        r = consulta()
        texto = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=str)
        r = {"estado": "ok"} if marca.lower() in texto.lower() else {
            "estado": "formato_cambiado", "motivo": "responde, pero el resultado ya no trae lo esperado"}
    except FuenteError as e:  # la web contestó, pero la consulta falló: puede ser pasajero
        r = {"estado": "a_revisar", "motivo": str(e)[:160]}
    except Exception as e:  # noqa: BLE001  (el código no encontró la estructura que esperaba: la web ha cambiado)
        r = {"estado": "formato_cambiado", "motivo": f"el conector no entiende la respuesta ({type(e).__name__})"}
    salida[nombre] = {**r, "segundos": round(time.monotonic() - inicio, 1)}


def fuentes() -> list[dict]:
    """Estado de cada fuente (petición ligera de estado.py) y, a las que responden, su canario."""
    sondeo = {f["fuente"]: f for f in _estado.estado()["fuentes"]}
    pruebas, resultado = canarios(), {}
    hilos = [threading.Thread(target=_canario, args=(n, *pruebas[n], resultado), daemon=True)
             for n in pruebas if sondeo.get(n, {}).get("estado") != "caída"]
    for h in hilos:
        h.start()
    fin = time.monotonic() + PLAZO_CANARIO
    for h in hilos:
        h.join(max(0.1, fin - time.monotonic()))
    salida = []
    for n, s in sondeo.items():
        if s["estado"] == "caída":
            salida.append({"fuente": n, "estado": "sin_respuesta", "motivo": s.get("motivo", "")})
        elif n in pruebas:
            salida.append({"fuente": n, **resultado.get(n, {"estado": "a_revisar", "motivo": "el canario no terminó a tiempo"})})
        else:
            salida.append({"fuente": n, "estado": "ok" if s["estado"] in ("ok", "lenta") else s["estado"],
                           "nota": "solo se ha comprobado que la web responde"})
    return salida


def _fila(que: str, estado: str, detalle: str) -> dict:
    return {"que": que, "estado": estado, "detalle": detalle}


def _entorno(herramientas: list[str]) -> list[dict]:
    filas = []
    v = sys.version_info
    filas.append(_fila("Python", "ok" if v >= (3, 11) else "mal", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
                       + ("" if v >= (3, 11) else ": hace falta la 3.11 o posterior")))
    manifiesto = RAIZ / ".claude-plugin" / "plugin.json"
    if manifiesto.is_file():
        try:
            m = json.loads(manifiesto.read_text(encoding="utf-8"))
            filas.append(_fila("Plugin", "ok", f"{m.get('name')} {m.get('version')} en {RAIZ}"))
        except (OSError, ValueError):
            filas.append(_fila("Plugin", "mal", f"{manifiesto} no se puede leer: reinstala el plugin"))
    else:
        filas.append(_fila("Plugin", "aviso", f"copia de desarrollo en {RAIZ} (sin .claude-plugin)"))
    if "onedrive" in str(RAIZ).lower() or "onedrive" in str(rutas.ruta("datos")).lower():
        filas.append(_fila("OneDrive", "aviso", f"el plugin o sus datos están dentro de OneDrive u otra nube: puede "
                           f"sincronizar y bloquear archivos ({_FAQ})"))
    skills = SKILLS[perfil.PERFIL]
    if (RAIZ / "skills").is_dir():
        faltan = [s for s in skills if not (RAIZ / "skills" / s / "SKILL.md").is_file()]
        filas.append(_fila("Skills", "mal" if faltan else "ok", f"faltan: {', '.join(faltan)}" if faltan else
                           f"{len(skills)} en su sitio"))
    datos = rutas.ruta("datos")
    filas.append(_fila("Datos", "ok" if datos.is_dir() else "aviso",
                       f"{datos}" + ("" if datos.is_dir() else " (se crea al guardar algo)")))
    faltan = _BASICAS - set(herramientas)
    filas.append(_fila("Herramientas", "mal" if faltan else "ok", f"{len(herramientas)} en el servidor"
                       + (f"; faltan {', '.join(sorted(faltan))}" if faltan else "")))
    filas.append(_fila("Claude in Chrome", "aviso", "no se puede comprobar desde el conector. Lo usan las skills de "
                       "ordenanzas" + ("" if perfil.LIGHT else ", CENDOJ y boletines de convenios") +
                       ": pregúntale a Claude si tiene sus herramientas de navegador"))
    if not perfil.LIGHT:
        filas.append(_indice_borme())
    return filas


def _indice_borme() -> dict:
    import sqlite3

    import borme_indice
    if not borme_indice.RUTA.is_file():
        return _fila("Índice del BORME", "aviso", "no creado (solo hace falta para ficha_empresa). Se crea en segundo "
                     "plano: el último año, unos 15 minutos; todo desde 2016, unas 2 horas. Órdenes: ficha_empresa con "
                     "cualquier nombre las da.")
    try:
        con = sqlite3.connect(f"{borme_indice.RUTA.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            desde, hasta = con.execute("SELECT MIN(fecha), MAX(fecha) FROM dias").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return _fila("Índice del BORME", "aviso", "existe pero no se puede leer (¿se está creando ahora?)")
    return _fila("Índice del BORME", "ok" if desde else "aviso",
                 f"del {borme_indice._iso(desde)} al {borme_indice._iso(hasta)}" if desde else "vacío: créalo con ficha_empresa")


def _siguiente(filas: list[dict], fuentes_: list[dict] | None) -> tuple[str, str]:
    """(resumen, siguiente paso), en lenguaje llano y por orden de gravedad."""
    mal = {f["que"]: f for f in filas if f["estado"] == "mal"}
    if "Python" in mal:
        return ("Falta una versión de Python que sirva.",
                "Instala Python 3.11 o posterior desde python.org (marca 'Add python.exe to PATH') y reinicia Claude Code.")
    if mal:
        return (f"Algo no está en su sitio: {', '.join(mal)}.",
                f"Vuelve a copiar la carpeta del plugin, reinicia Claude Code y repite el diagnóstico ({_FAQ}).")
    if fuentes_ is not None:
        rotas = [f for f in fuentes_ if f["estado"] == "formato_cambiado"]
        caidas = [f for f in fuentes_ if f["estado"] == "sin_respuesta"]
        dudosas = [f for f in fuentes_ if f["estado"] == "a_revisar"]
        if rotas:
            nombres = ", ".join(f["fuente"] for f in rotas)
            return (f"La web de {nombres} ha cambiado y el conector ya no la entiende.",
                    ("Apúntalo con la skill feedback (sin datos de clientes); mientras tanto, consulta esa fuente en su "
                     "web oficial." if not perfil.LIGHT else
                     "Hasta que se actualice el conector, consulta esa fuente en su web oficial."))
        if caidas:
            return (f"No responden ahora: {', '.join(f['fuente'] for f in caidas)}. No es un fallo del conector.",
                    "Reintenta en unos minutos; mientras tanto, lo de esas fuentes es 'no se pudo comprobar', nunca 'no consta'.")
        if dudosas:
            return (f"{', '.join(f['fuente'] for f in dudosas)} responde pero la consulta de control ha fallado.",
                    "Repite el diagnóstico en unos minutos; si sigue igual, es un cambio de la web.")
    avisos = [f for f in filas if f["estado"] == "aviso" and f["que"] in ("OneDrive", "Índice del BORME")]
    if avisos:
        return ("Todo funciona; hay un aviso.", f"{avisos[0]['que']}: {avisos[0]['detalle']}")
    return ("Todo en orden.", "Prueba con una de las preguntas de la skill fuentes-ayuda ('qué puedo preguntar').")


def informe(herramientas: list[str], con_fuentes: bool = True) -> dict:
    filas = _entorno(herramientas)
    fuentes_ = fuentes() if con_fuentes else None
    resumen, paso = _siguiente(filas, fuentes_)
    return {"resumen": resumen, "siguiente_paso": paso, "version": VERSION, "perfil": perfil.PERFIL, "copia": MARCA,
            "comprobaciones": filas,
            **({"fuentes": fuentes_, "criterio_fuentes": "ok: responde y la consulta de control sale como se espera; "
                "sin_respuesta: la web no contesta (red o caída); a_revisar: responde pero la consulta falló; "
                "formato_cambiado: responde, pero la web ya no tiene la forma que el conector entiende."}
               if fuentes_ is not None else {"fuentes": "no comprobadas (con_fuentes=False)"}),
            "hecho_por": perfil.creditos()}
