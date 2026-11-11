# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Catastro (datos no protegidos), VIES (NIF-IVA europeo) y BDNS (subvenciones): APIs oficiales."""
from __future__ import annotations

import difflib
import re

from red import FuenteError, corto, json_
from boe import _lista, _sin_acentos, fecha_aaaammdd, fecha_ddmmaaaa

CATASTRO = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCallejero.svc/json"
VIES = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms"
BDNS = "https://www.infosubvenciones.es/bdnstrans/api"


# Terminaciones de dominios públicos españoles y de la UE (administración general, autonómicas, diputaciones,
# ayuntamientos en .es). Un enlace fuera de ellas no se da: podría imitar a uno oficial.
_OFICIALES = (".gob.es", ".europa.eu", ".gencat.cat", ".euskadi.eus", ".xunta.gal", ".gva.es", ".madrid.org",
              ".juntadeandalucia.es", ".jcyl.es", ".castillalamancha.es", ".aragon.es", ".asturias.es", ".carm.es",
              ".cantabria.es", ".larioja.org", ".caib.es", ".gobiernodecanarias.org", ".juntaex.es", ".navarra.es",
              ".boe.es", ".sede.gob.es")


def _enlace(u) -> str | None:
    """URL que publica la fuente (fuera de la lista blanca): solo si es https, de forma normal y de un dominio
    público conocido. El nombre del campo ('..._enlace_externo') y el aviso_datos dicen que no está verificada."""
    m = isinstance(u, str) and re.fullmatch(r"https://([A-Za-z0-9.-]{1,100})(/[^\s\"'<>]{0,300})?", u)
    return u if m and ("." + m.group(1).lower()).endswith(_OFICIALES) else None


def _primeros(x, n: int = 500) -> list:
    """Los n primeros de una lista de la fuente, cortados ANTES de recorrerla: una respuesta con millones de
    elementos no se convierte entera (como mucho se devuelven 100)."""
    return _lista(x)[:n]


def _rc(rc: dict) -> str:
    return "".join(rc.get(k, "") for k in ("pc1", "pc2", "car", "cc1", "cc2"))


def _direccion(dt: dict) -> str | None:
    """Monta la dirección cuando el Catastro la da por partes (listas de inmuebles) y no en 'ldt'."""
    lourb = dt.get("locs", {}).get("lous", {}).get("lourb", {})
    d, loint = lourb.get("dir", {}), lourb.get("loint", {})
    if not d:
        return None
    interior = " ".join(f"{k} {v}" for k, v in (("Es", loint.get("es")), ("Pl", loint.get("pt")), ("Pt", loint.get("pu"))) if v)
    return " ".join(filter(None, (d.get("tv"), d.get("nv"), d.get("pnp"), interior, lourb.get("dp"),
                                  dt.get("nm"), f"({dt.get('np')})" if dt.get("np") else None)))


def _inmueble(bi: dict) -> dict:
    dt, debi = bi.get("dt", {}), bi.get("debi", {})
    rc = bi.get("rc") or bi.get("idbi", {}).get("rc", {})  # las listas lo traen en 'rc'; la ficha, en 'idbi'
    ref = _rc(rc) if isinstance(rc, dict) else ""
    return {"referencia_catastral": ref, "direccion": bi.get("ldt") or _direccion(dt),
            "fuente": f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx?RefC={ref}"
            if re.fullmatch(r"[0-9A-Z]{14,20}", ref) else None,
            "clase": bi.get("idbi", {}).get("cn"), "uso": debi.get("luso"),
            "superficie_construida_m2": debi.get("sfc"), "coeficiente_participacion": debi.get("cpt"),
            "año_construccion": debi.get("ant"), "municipio": dt.get("nm"), "provincia": dt.get("np")}


def consultar_catastro(referencia_catastral: str) -> dict:
    rc = re.sub(r"[\s.-]", "", referencia_catastral).upper()
    if not re.fullmatch(r"[0-9A-Z]{14}([0-9A-Z]{4}[A-Z]{2})?", rc):
        raise ValueError("La referencia catastral tiene 14 caracteres (parcela) o 20 (inmueble).")
    return _ficha(json_(f"{CATASTRO}/Consulta_DNPRC", {"RefCat": rc}).get("consulta_dnprcResult", {}), rc)


def _ficha(r: dict, rc: str) -> dict:
    """Respuesta del Catastro (por referencia o por polígono y parcela) -> inmueble con su finca, o lista."""
    if not isinstance(r, dict):
        raise FuenteError("El Catastro devolvió una respuesta que no se puede leer; reintenta.")
    if r.get("lerr"):
        raise FuenteError("Catastro: " + "; ".join(str(e.get("des", ""))[:200] for e in _primeros(r["lerr"], 5)
                                                   if isinstance(e, dict)))
    bico = r.get("bico")
    if bico and not rc:  # por polígono y parcela: la referencia la da el Catastro
        rc = _rc((bico.get("bi") or {}).get("idbi", {}).get("rc") or {})
        if not re.fullmatch(r"[0-9A-Z]{14}([0-9A-Z]{4}[A-Z]{2})?", rc):
            raise FuenteError("El Catastro no devolvió una referencia catastral reconocible.")
    if bico:  # un solo inmueble: viene con su finca y sus construcciones
        finca = bico.get("finca", {})
        return {"inmueble": _inmueble(bico.get("bi", {})),
                "finca": {"direccion": finca.get("ldt"), "tipo": finca.get("ltp"),
                          "superficie_suelo_m2": finca.get("dff", {}).get("ss"),
                          "cartografia_enlace_externo": _enlace(finca.get("infgraf", {}).get("igraf"))},
                "construcciones": [{"uso": c.get("lcd"), "m2": c.get("dfcons", {}).get("stl"),
                                    "tipo": c.get("dvcons", {}).get("dtip")} for c in _primeros(bico.get("lcons"))],
                "fuente": f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx?RefC={rc}",
                "aviso": "Solo datos no protegidos. Titular y valor catastral requieren certificado en la Sede del Catastro."}
    inmuebles = [_inmueble(x) for x in _primeros(r.get("lrcdnp", {}).get("rcdnp"))]
    rc = rc or (inmuebles[0]["referencia_catastral"][:14] if inmuebles else "")
    if not re.fullmatch(r"[0-9A-Z]{14}([0-9A-Z]{4}[A-Z]{2})?", rc):
        raise FuenteError("El Catastro no devolvió ningún inmueble reconocible.")
    return {"parcela": rc, "total_inmuebles": len(inmuebles),
            "fuente": f"https://www1.sedecatastro.gob.es/CYCBienInmueble/OVCConCiud.aspx?RefC={rc}", "inmuebles": inmuebles[:100],
            "uso": "Para el detalle de uno, consulta su referencia de 20 caracteres."}


# Tipos de vía (castellano, catalán, gallego, euskera) y artículos que se quitan del nombre de la calle: la vía se
# busca por su nombre en el callejero oficial del Catastro, que dice su tipo.
_TIPOS_VIA = {**dict.fromkeys(("c", "cl", "calle", "carrer", "kalea"), "CL"), "rua": "RU",  # rúa gallega: RU
              **dict.fromkeys(("av", "avda", "avenida", "avinguda", "etorbidea"), "AV"),
              **dict.fromkeys(("ps", "paseo", "passeig", "pasealekua"), "PS"),
              **dict.fromkeys(("pza", "pz", "plaza", "placa", "praza", "enparantza"), "PZ"),
              **dict.fromkeys(("ctra", "carretera"), "CR"), **dict.fromkeys(("camino", "cami"), "CM"),
              **dict.fromkeys(("travesia", "travessera"), "TR"), **dict.fromkeys(("pasaje", "passatge"), "PJ"),
              "ronda": "RD", "glorieta": "GL", "rambla": "RB", "callejon": "CJ", "urbanizacion": "UR",
              "poligono": "PG", "via": "VI", "cuesta": "CU", "bulevar": "BV", "plazuela": "PL"}


def _mayus(s: str) -> str:
    """Como lo escribe el Catastro: mayúsculas sin tildes, pero con Ñ y Ç (sin ellas no encuentra 'A CORUÑA' ni
    'CL COMERÇ', y daría otra calle parecida)."""
    s = s.replace("ñ", "\1").replace("Ñ", "\1").replace("ç", "\2").replace("Ç", "\2")
    return " ".join(_sin_acentos(s).replace("\1", "Ñ").replace("\2", "Ç").upper().split())


_ARTICULOS = {"de", "del", "la", "las", "los", "el", "d", "l", "dels", "da", "do", "das", "dos"}
_ALIAS_PROVINCIA = {"alicante": "alacant", "castellon": "castello", "la coruna": "a coruna", "coruna": "a coruna",
                    "orense": "ourense", "lerida": "lleida", "gerona": "girona", "baleares": "illes balears",
                    "islas baleares": "illes balears", "santa cruz de tenerife": "s c tenerife",
                    "tenerife": "s c tenerife"}
# Nombre en castellano -> como lo titula el Catastro (que usa el oficial, a menudo solo en la lengua cooficial).
_ALIAS_MUNICIPIO = {"palma de mallorca": "palma", "castellon": "castello de la plana",
                    "castellon de la plana": "castello de la plana", "jativa": "xativa", "villarreal": "vila-real",
                    "sagunto": "sagunt", "elche": "elx", "lerida": "lleida", "gerona": "girona", "orense": "ourense",
                    "la coruna": "a coruna", "hospitalet": "l'hospitalet de llobregat",
                    "hospitalet de llobregat": "l'hospitalet de llobregat", "la laguna": "san cristobal de la laguna"}
_FORALES = {"alava", "araba", "vizcaya", "bizkaia", "guipuzcoa", "gipuzkoa", "navarra", "nafarroa"}


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _sin_acentos(s).lower()).split())


def _elegir(buscado: str, nombres: list[str], que: str) -> str:
    """El nombre oficial que corresponde a lo escrito ('Alicante' -> 'ALICANTE/ALACANT'), o un error que orienta."""
    exactos = [n for n in nombres if buscado in (_norm(n), *(_norm(p) for p in n.split("/")))]
    if len(exactos) == 1 or (exactos and len(set(exactos)) == 1):
        return exactos[0]
    parecidos = exactos or [n for n in nombres if buscado in _norm(n)]
    if len(parecidos) == 1:
        return parecidos[0]
    if not parecidos:
        raise ValueError(f"El Catastro no tiene {que} {buscado!r}.")
    raise ValueError(f"Hay varios {que}s parecidos a {buscado!r}: {', '.join(str(p)[:60] for p in parecidos[:12])}. "
                     "Escríbelo entero.")


_ARTICULOS_FINALES = {"DE", "DEL", "D", "LA", "EL", "LOS", "LAS", "L"}  # al final del nombre de una vía


def _provincia_municipio(provincia: str, municipio: str) -> tuple[str, str]:
    """Nombres oficiales del Catastro para lo que escribe una persona ('Alicante', 'Elche' -> 'ALICANTE/ALACANT',
    'ELX'), o un error que orienta."""
    prov = _norm(provincia)
    prov = _ALIAS_PROVINCIA.get(prov, prov)
    if prov in _FORALES:
        raise ValueError("País Vasco y Navarra tienen catastro foral propio (diputaciones forales y Gobierno de "
                         "Navarra): sus inmuebles no están en el Catastro estatal.")
    provincias = [p.get("np", "") for p in _primeros(json_(f"{CATASTRO}/ObtenerProvincias").get(
        "consulta_provincieroResult", {}).get("provinciero", {}).get("prov"))]
    prov = _elegir(prov, provincias, "provincia")
    municipio = _ALIAS_MUNICIPIO.get(_norm(municipio), municipio)
    obtener = lambda nombre: [m.get("nm", "") for m in _primeros(json_(f"{CATASTRO}/ObtenerMunicipios", {  # noqa: E731
        "Provincia": prov, "Municipio": nombre}).get("consulta_municipieroResult", {}).get("municipiero", {}).get("muni"))
        if isinstance(m, dict)]
    municipios = obtener(_mayus(municipio))
    if not municipios:  # nada que empiece así: se ofrecen los más parecidos de la provincia
        parecidos = difflib.get_close_matches(_norm(municipio)[:80], [_norm(m)[:80] for m in obtener("")[:20_000]], n=5,
                                              cutoff=0.6)
        raise ValueError(f"El Catastro no tiene el municipio {municipio!r} en {prov}."
                         + (f" ¿Quizá {', '.join(p.upper() for p in parecidos)}?" if parecidos else
                            " Prueba con su nombre oficial (a veces solo en la lengua cooficial)."))
    return prov, _elegir(_norm(municipio), municipios, "municipio")


def buscar_catastro_por_direccion(provincia: str, municipio: str, calle: str, numero: str,
                                  tipo_via: str = "") -> dict:
    prov, muni = _provincia_municipio(provincia, municipio)
    # 'C/ Alcalá', 'Paseo de la Castellana', 'Avinguda Diagonal' -> tipo PS/AV... y nombre 'CASTELLANA', 'DIAGONAL'.
    palabras = _mayus(calle.replace("/", " ")).split()
    tipo = _TIPOS_VIA.get(_norm(tipo_via), _norm(tipo_via).upper())
    while len(palabras) > 1 and (_norm(palabras[0]) in _TIPOS_VIA or _norm(palabras[0]) in _ARTICULOS):  # 'Rúa do Paseo'
        tipo = tipo or _TIPOS_VIA.get(_norm(palabras[0]), "")
        palabras.pop(0)
    nombre = " ".join(palabras)
    if not nombre:
        raise ValueError("Indica el nombre de la calle.")
    vias = [c.get("dir", {}) for c in _primeros(json_(f"{CATASTRO}/ObtenerCallejero", {
        "Provincia": prov, "Municipio": muni, "TipoVia": "", "NomVia": nombre}).get(
        "consulta_callejeroResult", {}).get("callejero", {}).get("calle"))]
    nombre = _norm(nombre)
    # Solo el nombre exacto: una vía parecida ('COMERCIAL' por 'COMERÇ') daría datos de otra calle.
    # El Catastro pone el artículo al final ('CONSTITUCION (DE LA)', 'JUST OLIVERAS DE') o el barrio detrás
    # ('HERRADORES  en  SAN CRISTOBAL'): se compara sin eso, y se consulta con su nombre tal cual.
    def nombre_base(nv: str) -> str:
        nv = (nv or "")[:200]  # antes de nada: el nombre viene de la fuente, sin tope (ronda 13)
        i = nv.lower().find("  en  ")
        nv = (nv[:i] if i >= 0 else nv).rstrip()
        if nv.endswith(")") and 0 <= len(nv) - 1 - nv.rfind("(") <= 13:  # '(DE LA)' al final
            nv = nv[:nv.rfind("(")]
        palabras = nv.split()  # sin regex: 'DE LA' repetido hacía la regex exponencial (ronda 12)
        while len(palabras) > 1 and palabras[-1].upper() in _ARTICULOS_FINALES:
            palabras.pop()
        return _norm(" ".join(palabras))
    candidatas = [v for v in vias if isinstance(v, dict) and nombre_base(v.get("nv", "")) == nombre]
    if tipo and len(candidatas) > 1:
        candidatas = [v for v in candidatas if v.get("tv") == tipo] or candidatas
    if not candidatas:
        parecidas = ", ".join(f"{str(v.get('tv'))[:10]} {str(v.get('nv'))[:60]}" for v in vias[:12])
        raise ValueError(f"No hay ninguna vía llamada {nombre!r} en {muni} según el Catastro."
                         + (f" Parecidas: {parecidas}. Escribe el nombre como una de ellas." if parecidas else ""))
    if len({(v.get("tv"), v.get("nv")) for v in candidatas}) > 1:
        opciones = ", ".join(f"{str(v.get('tv'))[:10]} {str(v.get('nv'))[:60]}" for v in candidatas[:12])
        raise ValueError(f"Hay varias vías posibles en {muni}: {opciones}. Indica el tipo de vía (tipo_via) o el "
                         "nombre completo.")
    via = candidatas[0]
    params = {"Provincia": prov, "Municipio": muni, "Sigla": via.get("tv", ""), "Calle": via.get("nv", ""),
              "Numero": str(numero).strip()}
    r = json_(f"{CATASTRO}/Consulta_DNPLOC", params).get("consulta_dnplocResult", {})
    errores = [e.get("des") for e in _primeros(r.get("lerr"))]
    fuente = "https://www1.sedecatastro.gob.es/"
    usada = f"{via.get('tv')} {via.get('nv')}, {muni} ({prov})"  # siempre se dice qué vía se ha consultado
    if r.get("lrcdnp") or r.get("bico"):
        refs = [_inmueble(x) for x in _primeros(r.get("lrcdnp", {}).get("rcdnp"))] or [_inmueble((r.get("bico") or {}).get("bi") or {})]
        return {"via_consultada": usada, "total": len(refs), "inmuebles": refs[:100], "fuente": fuente,
                "uso": "Ficha de cada inmueble: catastro_referencia con su referencia catastral."}
    cercanos = [{"numero": n.get("num", {}).get("pnp"), "parcela": n.get("pc", {}).get("pc1", "") + n.get("pc", {}).get("pc2", "")}
                for n in _primeros(r.get("numerero", {}).get("nump"))]
    if cercanos:
        return {"via_consultada": usada, "total": 0, "aviso": "; ".join(filter(None, errores)) or "Número no encontrado.",
                "numeros_cercanos": cercanos, "fuente": fuente}
    raise FuenteError(f"Catastro ({via.get('tv')} {via.get('nv')}, {numero}, {muni}): "
                      + ("; ".join(filter(None, errores)) or "sin resultados."))


def catastro_por_parcela(provincia: str, municipio: str, poligono: str, parcela: str) -> dict:
    """Finca rústica por polígono y parcela (como figura en la escritura o en la PAC)."""
    pol, par = str(poligono).strip(), str(parcela).strip()
    if not (re.fullmatch(r"[0-9]{1,3}", pol) and re.fullmatch(r"[0-9]{1,5}", par)):
        raise ValueError("Polígono (hasta 3 cifras) y parcela (hasta 5 cifras), solo números: '12' y '345'.")
    prov, muni = _provincia_municipio(provincia, municipio)
    r = json_(f"{CATASTRO}/Consulta_DNPPP", {"Provincia": prov, "Municipio": muni, "Poligono": pol,
                                              "Parcela": par}).get("consulta_dnpppResult", {})
    return {"consultado": f"Polígono {pol}, parcela {par}, {muni} ({prov})", **_ficha(r, "")}


_COORDENADAS = "https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/COVCCoordenadas.svc/json"


def catastro_por_coordenadas(latitud: float | str, longitud: float | str) -> dict:
    """Parcela en un punto (grados decimales, WGS84, como los da Google Maps: 40.45305, -3.68845)."""
    try:
        lat, lon = (float(str(v).strip().replace(",", ".")[:20]) for v in (latitud, longitud))
    except ValueError:
        raise ValueError("Latitud y longitud en grados decimales: 40.45305 y -3.68845.") from None
    if not (27.5 <= lat <= 44 and -18.5 <= lon <= 4.5):  # península, Baleares, Canarias, Ceuta y Melilla
        raise ValueError("Ese punto no está en España (latitud 27,5 a 44; longitud -18,5 a 4,5). ¿Están al revés?")
    r = json_(f"{_COORDENADAS}/Consulta_RCCOOR", {"SRS": "EPSG:4326", "CoorX": f"{lon:.6f}", "CoorY": f"{lat:.6f}"})
    r = r.get("Consulta_RCCOORResult", {}) if isinstance(r, dict) else {}
    coord = next(iter(_primeros((r.get("coordenadas") or {}).get("coord"), 1)), None)
    pc = coord.get("pc", {}) if isinstance(coord, dict) else {}
    rc = f"{pc.get('pc1', '')}{pc.get('pc2', '')}" if isinstance(pc, dict) else ""
    if not re.fullmatch(r"[0-9A-Z]{14}", rc):
        error = "; ".join(str(e.get("des", ""))[:200] for e in _primeros(r.get("lerr"), 3) if isinstance(e, dict))
        return {"latitud": lat, "longitud": lon, "total": 0, "fuente": "https://www1.sedecatastro.gob.es/",
                "aviso": f"El Catastro no tiene parcela en ese punto ({error or 'sin referencia'}): suele ser vía "
                         "pública, o País Vasco y Navarra (catastro foral). Afina el punto sobre la finca."}
    return {"latitud": lat, "longitud": lon, "direccion_en_el_punto": corto(coord.get("ldt"), 300),
            **consultar_catastro(rc)}


def validar_nif_iva(nif_iva: str) -> dict:
    """NIF-IVA intracomunitario, p. ej. 'ESB12345678' o 'FR40303265045'."""
    v = re.sub(r"[\s.-]", "", nif_iva).upper()
    if re.fullmatch(r"[0-9A-Z][0-9]{7}[0-9A-Z]", v):  # NIF español sin prefijo: 'B12345678' -> 'ESB12345678'
        v = "ES" + v
    m = re.fullmatch(r"([A-Z]{2})([0-9A-Z+*]{2,13})", v)
    if not m:
        raise ValueError("Formato: código de país de 2 letras + número (ej. ESB12345678).")
    pais, numero = m.groups()
    if pais == "ES" and re.fullmatch(r"[0-9XYZKLM][0-9]{7}[A-Z]", numero):  # regla 3: el NIF-IVA de un autónomo es su DNI
        raise ValueError("Ese NIF-IVA es el DNI o NIE de una persona física: el conector no lo envía (regla 3). Solo "
                         "NIF-IVA de sociedades (ESB12345678) o de otros países.")
    pais = "EL" if pais == "GR" else pais  # VIES usa EL para Grecia
    r = json_(f"{VIES}/{pais}/vat/{numero}")
    if r.get("userError") == "INVALID_INPUT":
        extra = (" Tras el Brexit, VIES ya no cubre el Reino Unido; Irlanda del Norte usa el prefijo XI."
                 if pais == "GB" else "")
        raise ValueError(f"VIES no admite {pais}{numero}: el código de país o el formato del número no son válidos.{extra}")
    if r.get("userError") not in ("VALID", "INVALID"):
        raise FuenteError(f"VIES no ha podido comprobarlo ahora ({str(r.get('userError'))[:40]}). Reintenta más tarde.")
    return {"nif_iva": pais + numero, "valido": r.get("isValid"), "nombre": corto(r.get("name"), 300),
            "direccion": corto(r.get("address"), 500), "consultado": r.get("requestDate"),
            "fuente": "https://ec.europa.eu/taxation_customs/vies/",
            "nota": "valido=false solo significa que no está dado de alta como operador intracomunitario (ROI/VIES), no "
                    "que el NIF no exista. '---' = el Estado miembro no publica nombre ni dirección (España no los "
                    "publica)."}


def buscar_subvenciones(texto: str | None = None, desde: str | None = None, hasta: str | None = None,
                        max_resultados: int = 20) -> dict:
    if desde and hasta and fecha_aaaammdd(desde) > fecha_aaaammdd(hasta):
        raise ValueError("'desde' es posterior a 'hasta'.")
    params = {"page": 0, "pageSize": max(1, min(max_resultados, 50)), "order": "fechaRecepcion", "direccion": "desc"}
    if texto:
        params["descripcion"] = texto
    for clave, valor in (("fechaDesde", desde), ("fechaHasta", hasta)):
        if valor:
            params[clave] = fecha_ddmmaaaa(valor)
    r = json_(f"{BDNS}/convocatorias/busqueda", params)
    return {"total": r.get("totalElements") or 0, "fuente": "https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias",
            "mostradas": "Como mucho 50, las más recientes; acota con texto o fechas para ver otras.",
            **({"nota": "La BDNS busca el texto tal cual en la descripción de la convocatoria: con 0 resultados, prueba "
                        "con una sola palabra clave o sin fechas."} if texto and not r.get("totalElements") else {}),
            "convocatorias": [
        {"codigo_bdns": c.get("numeroConvocatoria"), "descripcion": corto(c.get("descripcion"), 1000),
         "fecha": c.get("fechaRecepcion"), "organo": " / ".join(filter(None, (c.get("nivel1"), c.get("nivel2"), c.get("nivel3")))),
         "fuente": f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias/{c.get('numeroConvocatoria')}"
         if re.fullmatch(r"[0-9]{1,9}", str(c.get("numeroConvocatoria"))) else None}
        for c in _primeros(r.get("content"), 50) if isinstance(c, dict)]}


def leer_convocatoria(codigo_bdns: str) -> dict:
    codigo = re.sub(r"^\s*bdns\s*:?\s*", "", str(codigo_bdns), flags=re.I).strip()  # 'BDNS 938946' -> '938946'
    if not re.fullmatch(r"[0-9]{1,9}", codigo):
        raise ValueError("El código BDNS es numérico (p. ej. 938946).")
    try:
        c = json_(f"{BDNS}/convocatorias", {"numConv": codigo})
    except FuenteError as e:
        if e.codigo == 404:
            raise FuenteError(f"No existe la convocatoria {codigo} en la BDNS.") from None
        raise FuenteError(f"La BDNS no responde ahora ({str(e)[:80]}); reintenta. No significa que no exista.") from None
    if not c or not c.get("codigoBDNS"):
        raise FuenteError(f"No existe la convocatoria {codigo} en la BDNS.")
    nombres = lambda clave: [x.get("descripcion") for x in _primeros(c.get(clave))]  # noqa: E731
    return {"codigo_bdns": c.get("codigoBDNS"), "descripcion": corto(c.get("descripcion")),
            "organo": c.get("organo"), "fecha": c.get("fechaRecepcion"), "tipo": c.get("tipoConvocatoria"),
            "presupuesto_total": c.get("presupuestoTotal"), "beneficiarios": nombres("tiposBeneficiarios"),
            "sectores": nombres("sectores"), "regiones": nombres("regiones"), "instrumentos": nombres("instrumentos"),
            "inicio_solicitud": c.get("fechaInicioSolicitud"), "fin_solicitud": c.get("fechaFinSolicitud"),
            "abierto": c.get("abierto"), "bases_reguladoras_enlace_externo": _enlace(c.get("urlBasesReguladoras")),
            "sede_electronica_enlace_externo": _enlace(c.get("sedeElectronica")),
            "fuente": f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatorias/{codigo}"}
