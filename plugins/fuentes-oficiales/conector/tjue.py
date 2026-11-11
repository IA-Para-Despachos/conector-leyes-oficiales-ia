# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Jurisprudencia de la UE (Tribunal de Justicia y Tribunal General) desde CELLAR, el repositorio de la Oficina de
Publicaciones de la UE: búsqueda con su consulta SPARQL pública y texto en español (XHTML). Su reutilización está
permitida (Decisión 2011/833/UE), sin cuenta ni clave. El enlace que se cita es el de EUR-Lex."""
from __future__ import annotations

import json
import re

import boe
from boe import _sin_acentos, fecha_aaaammdd
from red import FuenteError, Sesion, plano, recortar, tope

_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
_EURLEX = "https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:"
_P = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> "
      "PREFIX owl: <http://www.w3.org/2002/07/owl#> ")
_RECURSO = "http://publications.europa.eu/resource/"  # <.../celex/62019CJ0311>, <.../ecli/ECLI%3AEU%3AC%3A2020%3A981>
_SPA = "<http://publications.europa.eu/resource/authority/language/SPA>"
# Tipo de documento en el CELEX: sentencia (J), auto (O), conclusiones del Abogado General (C); C = Tribunal de
# Justicia, T = Tribunal General.
_TIPOS = {"sentencia": ("J",), "auto": ("O",), "conclusiones": ("C",), "todos": ("J", "O", "C")}
_TRIBUNALES = {"justicia": ("C",), "general": ("T",), "todos": ("C", "T")}
_CELEX = re.compile(r"6[0-9]{4}[CT][JOC][0-9]{4}(?:\([0-9]{2}\))?")


def _sparql(consulta: str) -> list[dict]:
    crudo = Sesion().texto(_SPARQL, {"query": consulta, "format": "application/sparql-results+json"},
                           cabeceras={"Accept": "application/sparql-results+json"}, timeout=60)
    try:
        datos = json.loads(crudo)
    except (ValueError, RecursionError):
        raise FuenteError("El repositorio de la UE no devolvió una respuesta válida.") from None
    filas = (datos.get("results") or {}).get("bindings") if isinstance(datos, dict) else None
    if not isinstance(filas, list):
        raise FuenteError("El repositorio de la UE no devolvió resultados válidos.")
    return [{k: str((v or {}).get("value", ""))[:2000] for k, v in f.items()} for f in filas[:500] if isinstance(f, dict)]


def _celex_de(ident: str) -> list[str]:
    """CELEX candidatos de un asunto ('C-311/19', 'asunto T‑123/20'), un ECLI o un CELEX."""
    t = " ".join(ident.replace("‑", "-").replace("–", "-").split()).upper()
    if (m := _CELEX.fullmatch(t)):
        return [m.group(0)]
    if (m := re.fullmatch(r"ECLI:EU:[CTF]:[0-9]{4}:[0-9]{1,6}", t)):
        # Por su URI (owl:sameAs), al momento; por el literal cdm:case-law_ecli, el repositorio tardaba 30-50 s.
        filas = _sparql(_P + f"SELECT ?celex WHERE {{ ?w owl:sameAs <{_RECURSO}ecli/{m.group(0).replace(':', '%3A')}> ; "
                        "cdm:resource_legal_id_celex ?celex }")
        return [f["celex"] for f in filas if _CELEX.fullmatch(f.get("celex", ""))]
    m = re.fullmatch(r"(?:ASUNTOS? )?([CT])-([0-9]{1,4})/([0-9]{2})", t)
    if not m:
        raise ValueError("Indica el asunto ('C-311/19', 'T-123/20'), el ECLI ('ECLI:EU:C:2020:981') o el CELEX "
                         "('62019CJ0311').")
    tribunal, numero, anno = m.groups()
    anno = ("19" if int(anno) > 50 else "20") + anno
    return [f"6{anno}{tribunal}{tipo}{int(numero):04d}" for tipo in "JOC"]


def _palabras(texto: str) -> list[str]:
    """Palabras para buscar en el título (solo letras y cifras: nada que pueda alterar la consulta)."""
    palabras = [p for p in re.findall(r"[a-z0-9ñ]+", _sin_acentos(texto.lower())) if len(p) > 2][:6]
    if not palabras:
        raise ValueError("Indica alguna palabra de la materia ('deducción IVA', 'tiempo de trabajo').")
    return palabras


def _patron(palabra: str) -> str:
    """La palabra como expresión regular que ignora tildes: 'deduccion' casa con 'deducción'."""
    tildes = {"a": "[aá]", "e": "[eé]", "i": "[ií]", "o": "[oó]", "u": "[uúü]", "n": "[nñ]"}
    return "".join(tildes.get(c, c) for c in palabra)


def acumulado(asunto: str) -> list[dict]:
    """Resoluciones de otro asunto cuyo título nombra este: en los asuntos acumulados, 'C-307/15' va en la sentencia
    de C-154/15. Solo en los 3 años anteriores al del asunto (el principal suele ser igual o anterior)."""
    m = re.fullmatch(r"([CT])-([0-9]{1,4})/([0-9]{2})", " ".join(asunto.replace("‑", "-").replace("–", "-").split()).upper())
    if not m:
        return []
    tribunal, numero, anno = m.groups()
    anno_ = int(("19" if int(anno) > 50 else "20") + anno)
    anos = "|".join(str(a) for a in range(anno_ - 3, anno_ + 1))
    filas = _sparql(_P + "SELECT DISTINCT ?celex ?ecli ?fecha ?titulo WHERE { ?w cdm:resource_legal_id_celex ?celex . "
                    f'FILTER(REGEX(STR(?celex), "^6({anos}){tribunal}[JOC]")) ?w cdm:work_date_document ?fecha . '
                    f"?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language {_SPA} ; cdm:expression_title "
                    f'?titulo . FILTER(REGEX(?titulo, "{tribunal}.{int(numero)}/{anno}[^0-9]")) '
                    "OPTIONAL { ?w cdm:case-law_ecli ?ecli } } LIMIT 20")
    vistos, r = set(), []
    for f in filas:
        if _CELEX.fullmatch(f.get("celex", "")) and f["celex"] not in vistos:
            vistos.add(f["celex"])
            r.append({"celex": f["celex"], "ecli": f.get("ecli") or None, "fecha": f.get("fecha", "")[:10],
                      "titulo": " ".join(f.get("titulo", "").replace("#", " · ").split())[:600],
                      "fuente": _EURLEX + f["celex"]})
    return r


def buscar_tjue(texto: str = "", asunto: str = "", desde: str = "", hasta: str = "", tribunal: str = "todos",
                tipo: str = "sentencia", max_resultados: int = 10) -> dict:
    tribunal, tipo = (tribunal or "todos").strip().lower(), (tipo or "sentencia").strip().lower()
    if tribunal not in _TRIBUNALES or tipo not in _TIPOS:
        raise ValueError("tribunal: justicia, general o todos; tipo: sentencia, auto, conclusiones o todos.")
    if asunto.strip():
        celex = _celex_de(asunto)
        filtro = "VALUES ?celex { " + " ".join(f'"{c}"^^xsd:string' for c in celex) + " }"
        donde = ""
    else:
        palabras = _palabras(texto)
        claves = "|".join(f"{t}{d}" for t in _TRIBUNALES[tribunal] for d in _TIPOS[tipo])
        filtro = (f'FILTER(REGEX(STR(?celex), "^6[0-9]{{4}}({claves})[0-9]{{4}}$")) '
                  + " ".join(f'FILTER(REGEX(STR(?titulo), "{_patron(p)}", "i"))' for p in palabras))
        donde = "".join(f' FILTER(?fecha {op} "{f[:4]}-{f[4:6]}-{f[6:]}"^^xsd:date)'
                        for op, f in ((">=", fecha_aaaammdd(desde) if desde else ""),
                                      ("<=", fecha_aaaammdd(hasta) if hasta else "")) if f)
    consulta = (_P + "SELECT DISTINCT ?celex ?ecli ?fecha ?titulo WHERE { " + filtro +
                " ?w cdm:resource_legal_id_celex ?celex . ?w cdm:work_date_document ?fecha ."
                f" ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language {_SPA} ; cdm:expression_title ?titulo ."
                " OPTIONAL { ?w cdm:case-law_ecli ?ecli }" + donde +
                f" }} ORDER BY DESC(?fecha) LIMIT {tope(max_resultados, 25) + 6}")
    vistos, resultados = set(), []
    for f in _sparql(consulta):
        celex = f.get("celex", "")
        if not _CELEX.fullmatch(celex) or celex in vistos:
            continue
        vistos.add(celex)
        titulo = " ".join(f.get("titulo", "").replace("#", " · ").split())
        resultados.append({"celex": celex, "ecli": f.get("ecli") or None, "fecha": f.get("fecha", "")[:10],
                           "titulo": titulo[:600], "fuente": _EURLEX + celex})
    hay_mas = len(resultados) > tope(max_resultados, 25)
    resultados = resultados[:tope(max_resultados, 25)]
    r = {"total": len(resultados), "resultados": resultados, "fuente": "https://eur-lex.europa.eu",
         "uso": "Texto o pasajes: leer_tjue(celex, buscar_en=...). Las que interpretan un artículo concreto de una "
                "norma: jurisprudencia_ue_articulo."}
    if hay_mas:
        r["aviso"] = ("Hay más resultados que los mostrados ('total' es lo mostrado, las más recientes): acota con más "
                      "palabras, el tipo, el tribunal o las fechas (desde/hasta).")
    if not resultados:
        r["aviso"] = ("No consta en el repositorio de la UE con ese asunto." if asunto.strip() else
                      "Ningún título de una resolución lleva todas esas palabras: el buscador mira el título (las partes "
                      "y las palabras clave del asunto). Prueba con menos palabras o con otras de la materia.")
    return r


def leer_tjue(ident: str, buscar_en: str = "", max_caracteres: int = 20000, desde: int = 0) -> dict:
    celex = _celex_de(ident)
    filas = _sparql(
        # Por la URI del CELEX: con el mismo CELEX hay a veces otras obras ('62015CJ0154_1'), copias antiguas sin la
        # rectificación; la obra principal es la que lleva la versión vigente.
        _P + "SELECT ?celex ?ecli ?fecha ?item ?tipo WHERE { VALUES ?u { "
        + " ".join(f"<{_RECURSO}celex/{c}>" for c in celex) + " } ?w owl:sameAs ?u ; cdm:resource_legal_id_celex ?celex ."
        " OPTIONAL { ?w cdm:case-law_ecli ?ecli } OPTIONAL { ?w cdm:work_date_document ?fecha }"
        f" ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language {_SPA} ."
        " ?m cdm:manifestation_manifests_expression ?e ; cdm:manifestation_type ?tipo . FILTER(STR(?tipo) = \"xhtml\")"
        " ?i cdm:item_belongs_to_manifestation ?m . BIND(STR(?i) AS ?item) }")
    # Primero la sentencia, luego el auto, luego las conclusiones (con un asunto, salen las tres si existen).
    filas = sorted((f for f in filas if _CELEX.fullmatch(f.get("celex", ""))), key=lambda f: "JOC".index(f["celex"][6]))
    item = next((f for f in filas if re.fullmatch(r"https?://publications\.europa\.eu/resource/cellar/[0-9a-f.-]{20,80}"
                                                    r"/DOC_[0-9]{1,3}", f.get("item", ""))), None)
    if not item:
        raise FuenteError(f"No hay texto en español de {ident.strip()[:30]} en el repositorio de la UE (puede no existir o "
                          "estar solo en otras lenguas).", 404)
    url = "https://" + item["item"].split("://", 1)[1]  # el repositorio da el enlace en http: se pide por https
    texto_ = plano(Sesion().texto(url, timeout=60)[:6_000_000])
    lineas = [" ".join(linea.split()) for linea in texto_.split("\n")]
    texto_ = "\n".join(linea for linea in lineas if linea)
    r = {"celex": item["celex"], "ecli": item.get("ecli") or None, "fecha": item.get("fecha", "")[:10],
         "tipo": {"J": "sentencia", "O": "auto", "C": "conclusiones del Abogado General"}[item["celex"][6]],
         "fuente": _EURLEX + item["celex"], "caracteres_en_total": len(texto_)}
    otros = [f["celex"] for f in filas if f["celex"] != item["celex"]]
    if otros:
        r["tambien_en_el_asunto"] = sorted(set(otros))
    i = texto_.rfind(" declara:")
    if i < 0:
        i = texto_.rfind("declara:")
    if i >= 0:  # el fallo: tras 'el Tribunal de Justicia (Sala ...) declara:' hasta las firmas
        fallo = texto_[texto_.rfind("\n", 0, i) + 1:]
        r["fallo"] = fallo[:4000].split("\nFirmas")[0].strip()
    if buscar_en.strip():
        return {**r, "buscar_en": buscar_en, **_pasajes(texto_, buscar_en)}
    return {**r, "texto": recortar(texto_, max_caracteres, desde)}


def _pasajes(texto_: str, buscar_en: str) -> dict:
    """Los párrafos donde aparecen todas las palabras (al principio de palabra, como en el BOE), con su apartado. El
    número va solo en su línea ('30') o, en las sentencias antiguas, delante del párrafo ('30. Por otro lado'): este
    último solo cuenta si sigue al anterior, para no tomar por apartado el '1.' de un artículo citado."""
    partes, ultimo = [("inicio", [])], 0
    for linea in texto_.split("\n"):
        m = re.match(r"([0-9]{1,3})(?:\. |$)", linea)
        if m and (m.end() == len(linea) or int(m.group(1)) == ultimo + 1):
            ultimo = int(m.group(1))
            partes.append((m.group(1), []))
            if m.end() == len(linea):
                continue
        partes[-1][1].append(linea)
    salida = boe.pasajes([(n, ps) for n, ps in partes if ps], buscar_en)
    salida["pasajes"] = [{"apartado": p["donde"], "texto": p["texto"]} for p in salida["pasajes"]]
    return salida