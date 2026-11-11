# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Normas de la UE (reglamentos, directivas, decisiones, Tratados y Carta) desde CELLAR, el repositorio de la Oficina
de Publicaciones: el artículo de la última versión consolidada en español y la búsqueda por el título. Reutilización
permitida (Decisión 2011/833/UE), sin cuenta ni clave. EUR-Lex solo se cita: su web exige JavaScript. También, qué
sentencias del TJUE interpretan un artículo (la relación 'Interpreta' de EUR-Lex)."""
from __future__ import annotations

import re
from datetime import date

from boe import _sin_acentos
from red import FuenteError, Sesion, plano, recortar, tope
from tjue import _CELEX as _CELEX_TJUE, _P, _SPA, _palabras, _patron, _sparql

_EURLEX = "https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:"
# Las más usadas en un despacho, por sigla o nombre corriente (sin tildes, en minúsculas) -> CELEX.
_CONOCIDAS = (
    ("32016R0679", "rgpd|gdpr|reglamento general de proteccion de datos"),
    ("12016E/TXT", "tfue|tratado de funcionamiento de la union europea"),
    ("12016M/TXT", "tue|tratado de la union europea"),
    ("12016P/TXT", "carta|cdfue|carta de los derechos fundamentales|carta de los derechos fundamentales de la union europea"),
    ("32006L0112", "directiva del iva|directiva iva"),
    ("31977L0388", "sexta directiva|sexta directiva del iva"),
    ("32011R0282", "reglamento de ejecucion del iva|reglamento de ejecucion iva"),
    ("32013R0952", "cau|codigo aduanero|codigo aduanero de la union"),
    ("32012R1215", "bruselas i bis"),
    ("32008R0593", "roma i"),
    ("32007R0864", "roma ii"),
    ("32011L0016", "dac|directiva de cooperacion administrativa"),
    ("32016L1164", "atad|directiva antielusion fiscal|directiva antielusion"),
    ("32011L0096", "directiva matriz filial|directiva matriz-filial"),
    ("32003L0088", "directiva de tiempo de trabajo|directiva del tiempo de trabajo"),
    ("31996L0071", "directiva de desplazamiento de trabajadores"),
    ("32001L0023", "directiva de traspasos de empresas|directiva de transmision de empresas"),
    ("31998L0059", "directiva de despidos colectivos"),
    ("31993L0013", "directiva de clausulas abusivas"),
    ("32011L0083", "directiva de derechos de los consumidores"),
    ("32011L0007", "directiva de morosidad"),
    ("32015R0848", "reglamento de insolvencia"),
    ("32012R0650", "reglamento de sucesiones|reglamento sucesorio europeo"),
)
SIGLAS = {alias: celex for celex, alias_ in _CONOCIDAS for alias in alias_.split("|")}
_CELEX = re.compile(r"[03][0-9]{4}[LRD][0-9]{4}(?:-[0-9]{8})?|1[0-9]{4}[EMP]/TXT")
_TIPOS = {"reglamento": "R", "directiva": "L", "decision": "D"}
_NUMERO = re.compile(r"(directiva|reglamento|decision)?(?: de ejecucion| delegad[oa])?(?: \((?:ue|ce|cee)(?:, euratom)?\)|"
                     r" (?:ue|ce|cee))?(?: n\.? ?[o°º]\.?)? ?([0-9]{2,4})/([0-9]{1,4})(/(?:ue|ce|cee|euratom))?")
_SUFIJOS = "bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies"
_TITULO_ART = re.compile(rf"Art[íi]culo ([0-9]{{1,4}})((?: (?:{_SUFIJOS})){{0,2}})")
_CABECERA = re.compile(r"(?:Secci[óo]n|Subsecci[óo]n|Cap[íi]tulo) [0-9IVX]{1,5}(?: bis)?(?: -)?$|Hecho en |\(no se reproduce|"
                       r"Por el Parlamento Europeo|Por el Consejo|Por la Comisi[óo]n|El presente Reglamento ser[áa] obligatorio|"
                       r"La presente Decisi[óo]n ser[áa] obligatoria")
_MARCA = re.compile(r"[►▼] ?(?:[BMACIRE][0-9]{0,4})? ?|◄")  # ►M27 ... ◄: qué norma dio cada trozo
_VINETA = re.compile(r"(?:[a-z]{1,2}|[0-9]{1,3}|[ivx]{1,6})[).]|\((?:[a-z]{1,2}|[0-9]{1,3}|[ivx]{1,6})\)|[\u2014\u2013-]")
_ITEM = re.compile(r"https?://publications\.europa\.eu/resource/cellar/[0-9a-f.-]{20,80}/DOC_([0-9]{1,3})")


def resolver(norma: str) -> str:
    """CELEX de la norma: sigla o nombre conocido, número ('Directiva 2006/112/CE', 'Reglamento (UE) 2016/679',
    'Reglamento 1215/2012') o CELEX. ValueError si no se identifica sin dudas."""
    crudo = " ".join((norma or "").split())[:200]
    if (m := _CELEX.fullmatch(crudo.upper())):
        return m.group(0)
    t = _sin_acentos(crudo.lower()).strip(" .,;")
    t = re.sub(r"^(?:el|la|los|del|de la) ", "", t)
    if t in SIGLAS:
        return SIGLAS[t]
    m = _NUMERO.fullmatch(t)
    if not m:
        raise ValueError("Indica la norma de la UE por su sigla (RGPD, TFUE, TUE, Carta, 'Directiva del IVA'...), su "
                         "número ('Directiva 2006/112/CE', 'Reglamento (UE) 2016/679') o su CELEX ('32016R0679'); si no la "
                         "conoces, búscala con buscar_norma_ue.")
    tipo, a, b, sufijo = m.groups()
    anno = lambda x: int(x) + (1900 if int(x) >= 50 else 2000) if len(x) == 2 else int(x)  # noqa: E731
    # Directivas y decisiones: año/número ('93/13', '2006/112'). Reglamentos: número/año hasta 2014 ('1215/2012'),
    # año/número desde 2015 ('2016/679').
    if tipo == "reglamento" and not (len(a) == 4 and 2015 <= int(a) <= date.today().year):
        if len(b) not in (2, 4):
            raise ValueError(f"No entiendo el número {a}/{b}: un reglamento anterior a 2015 va como número/año ('1215/2012').")
        numero, ano = int(a), anno(b)
    else:
        numero, ano = int(b), anno(a)
    if not 1950 <= ano <= date.today().year or numero > 9999:
        raise ValueError(f"No entiendo el número {a}/{b} de la norma.")
    if tipo:
        return f"3{ano}{_TIPOS[tipo]}{numero:04d}"
    # Año/número con '/CE' detrás ('2006/112/CE') solo lo llevan directivas y decisiones, nunca un reglamento.
    candidatos = [f"3{ano}{letra}{numero:04d}" for letra in ("LD" if sufijo else "RLD")]
    filas = _sparql(_P + "SELECT DISTINCT ?celex WHERE { VALUES ?celex { " + " ".join(f'"{c}"^^xsd:string' for c in candidatos)
                    + " } ?w cdm:resource_legal_id_celex ?celex }")
    hay = sorted({f.get("celex") for f in filas} & set(candidatos))
    if len(hay) != 1:
        raise ValueError(f"'{crudo[:60]}' no identifica una sola norma ({', '.join(hay) or 'ninguna'}): di si es "
                         "directiva, reglamento o decisión.")
    return hay[0]


def _ficha(celex: str) -> dict:
    """Metadatos de la norma y la versión que se lee: la última consolidada con fecha ya llegada que tenga texto en
    español (xhtml o html); si no hay, la original."""
    valor = f'"{celex}"^^xsd:string'
    filas = _sparql(  # en xhtml van también sus imágenes (otros DOC_n): se pide el que es html
        _P + "PREFIX cmr: <http://publications.europa.eu/ontology/cdm/cmr#> SELECT ?celex ?vig ?fin ?fecha ?deroga ?titulo ?tipo ?item WHERE { { VALUES ?celex { " + valor + " } "
        "?x cdm:resource_legal_id_celex ?celex . OPTIONAL { ?x cdm:resource_legal_in-force ?vig } "
        "OPTIONAL { ?d cdm:resource_legal_repeals_resource_legal|cdm:resource_legal_implicitly_repeals_resource_legal ?x . "
        "?d cdm:resource_legal_id_celex ?deroga } "
        "OPTIONAL { ?x cdm:resource_legal_date_end-of-validity ?fin } OPTIONAL { ?x cdm:work_date_document ?fecha } } "
        "UNION { ?w cdm:resource_legal_id_celex " + valor + " . ?x cdm:act_consolidated_based_on_resource_legal ?w ; "
        "cdm:resource_legal_id_celex ?celex } "
        f"?e cdm:expression_belongs_to_work ?x ; cdm:expression_uses_language {_SPA} . "
        "OPTIONAL { ?e cdm:expression_title ?titulo } OPTIONAL { ?m cdm:manifestation_manifests_expression ?e ; "
        'cdm:manifestation_type ?tipo . FILTER(STR(?tipo) IN ("xhtml", "html")) '
        "?i cdm:item_belongs_to_manifestation ?m ; cmr:manifestationMimeType ?mime . FILTER(CONTAINS(STR(?mime), "
        '"html")) BIND(STR(?i) AS ?item) } }')
    propia = [f for f in filas if f.get("celex") == celex]
    if not propia:
        raise FuenteError(f"No consta {celex} en el repositorio de la UE con versión en español.", 404)
    hoy = date.today().strftime("%Y%m%d")
    versiones: dict[str, list] = {}  # celex -> [(xhtml primero, número de DOC, url)]
    for f in filas:
        m = _ITEM.fullmatch(f.get("item", ""))
        if m and (f["celex"] == celex or re.fullmatch(rf"0{celex[1:10]}-[0-9]{{8}}", f["celex"])):
            versiones.setdefault(f["celex"], []).append((f.get("tipo") != "xhtml", int(m.group(1)), m.group(0)))
    consolidadas = sorted(c for c in versiones if c.startswith("0") and c != celex)
    ya = [c for c in consolidadas if c[-8:] <= hoy]
    leida = celex if celex.startswith("0") else (ya[-1] if ya else celex)
    if leida not in versiones:
        raise FuenteError(f"No hay texto en español de {celex} en el repositorio de la UE (en xhtml o html).", 404)
    base = propia[0]
    titulo = next((f["titulo"] for f in filas if f.get("celex") == leida and f.get("titulo")), base.get("titulo", ""))
    url = lambda c: "https://" + sorted(versiones[c])[0][2].split("://", 1)[1]  # noqa: E731
    # Si la norma está derogada, su última consolidada suele ser solo la nota 'Derogada por': antes, las anteriores.
    anteriores = [c for c in reversed(ya) if c < leida][:2] + ([celex] if celex in versiones and leida != celex else [])
    return {"celex": celex, "leida": leida, "url": url(leida), "anteriores": [(c, url(c)) for c in anteriores],
            "titulo": " ".join(titulo.split())[:600], "vigente": base.get("vig"), "fin": base.get("fin", "")[:10],
            "fecha": base.get("fecha", "")[:10], "futuras": [c[-8:] for c in consolidadas if c[-8:] > hoy],
            "derogada_por": sorted({f["deroga"] for f in propia if _CELEX.fullmatch(f.get("deroga", ""))})}


_DOCS: dict[str, list[str]] = {}  # caché de la sesión: url -> líneas del texto (pocas, pesan)


def _lineas(url: str) -> list[str]:
    if url not in _DOCS:
        if len(_DOCS) >= 4:
            _DOCS.pop(next(iter(_DOCS)))
        lineas, vineta = [], ""
        crudo = Sesion().texto(url, timeout=60)
        if not crudo.lstrip("﻿ \r\n\t").startswith("<"):
            raise FuenteError("El repositorio de la UE no devolvió el texto en html; reintenta más tarde.")
        for linea in plano(crudo).split("\n"):
            linea = " ".join(_MARCA.sub(" ", linea).split())
            if not linea:
                continue
            if _VINETA.fullmatch(linea):  # 'a)' sola en su línea: va con el texto que la sigue
                vineta = (vineta + " " + linea).strip() if len(vineta) < 40 else linea  # sin acumular sin fin
                continue
            lineas.append((vineta + " " + linea).strip() if vineta else linea)
            vineta = ""
        _DOCS[url] = lineas
    return _DOCS[url]


def _pedido(articulo: str) -> tuple[str, bool]:
    """('17', False) de '17'; ('6', True) de '6.1.f)' (va el artículo entero); ('17 bis', False) de 'art. 17 bis'."""
    t = re.sub(r"^art(?:[ií]culo|\.)?\s*", "", " ".join(_sin_acentos((articulo or "").lower()).split())[:60])
    m = re.match(rf"([0-9]{{1,4}})((?: ?(?:{_SUFIJOS})\b){{0,2}})", t)
    if not m:
        raise ValueError("Indica el artículo ('17', '17 bis', '6.1.f)').")
    pedido = f"{int(m.group(1))} {' '.join(m.group(2).split())}".strip()
    return pedido, bool(t[m.end():].strip(" ."))


def _es_fin(linea: str) -> bool:
    letras = [c for c in linea[:150] if c.isalpha()]
    return bool(_TITULO_ART.fullmatch(linea) or _CABECERA.match(linea)
                or (len(linea) < 150 and len(letras) >= 4 and all(c.isupper() for c in letras)))


def articulo_ue(norma: str, articulo: str, max_caracteres: int = 30000) -> dict:
    celex = resolver(norma)
    pedido, con_apartado = _pedido(articulo)
    f = _ficha(celex)
    derogada = f["vigente"] == "0"
    sustituta = f"; la sustituye {', '.join(f.get('derogada_por') or [])}" if f.get("derogada_por") else ""
    derogada_o = "derogada" if f.get("derogada_por") else "derogada o caducada"
    no_vigente = f"no vigente desde {f['fin'] or 'fecha que no consta'}{sustituta}"
    # Derogada: su última consolidada suele traer solo la nota 'Derogada por'; se mira en las anteriores.
    for leida, url in [(f["leida"], f["url"])] + (f.get("anteriores", []) if derogada else []):
        lineas = _lineas(url)
        inicio = next((i for i, linea in enumerate(lineas) if (m := _TITULO_ART.fullmatch(linea))
                       and f"{int(m.group(1))} {' '.join(m.group(2).split())}".strip() == pedido), None)
        if inicio is not None:
            break
    f["leida"] = leida
    version = leida[-8:] if leida.startswith("0") else ""
    de_cuando = f"{version[:4]}-{version[4:6]}-{version[6:]}" if version else f["fecha"]
    if inicio is None and derogada:
        raise FuenteError(f"La norma {celex} está {derogada_o} ({no_vigente}, según el repositorio de la UE) y no encuentro el artículo "
                          f"{pedido} en sus últimas versiones.", 404)
    if inicio is None:
        raise FuenteError(f"No encuentro el artículo {pedido} en {leida} (versión de {de_cuando}): no existe, está "
                          "numerado de otra forma o se ha suprimido.", 404)
    fin = next((j for j in range(inicio + 1, len(lineas)) if _es_fin(lineas[j])), len(lineas))
    texto_ = "\n".join(lineas[inicio:fin])[:200_000]
    avisos = [f"ATENCIÓN: norma {derogada_o} ({no_vigente}, según el repositorio de la UE); es el texto de su última versión "
              f"con articulado ({de_cuando}). Para un hecho posterior, cita la norma que la sustituye."] if derogada else []
    if f["leida"].startswith("0"):
        avisos.append(f"Texto consolidado a {de_cuando} (versión que rige desde esa fecha): instrumento de documentación "
                      "de la Oficina de Publicaciones, sin efecto jurídico; el auténtico es el publicado en el DOUE "
                      "(fuente_doue). Puede no recoger aún una modificación muy reciente.")
    elif f["leida"].startswith("1"):
        avisos.append(f"Versión consolidada de los Tratados publicada en el DOUE (serie C) de {de_cuando}; es la última "
                      "que ha publicado la UE.")
    else:
        avisos.append("No hay versión consolidada en español: es el texto original publicado en el DOUE y no incluye "
                      "modificaciones posteriores, si las ha habido. Compruébalo.")
    if f["futuras"]:
        avisos.append(f"ATENCIÓN: hay versiones consolidadas con fecha que aún no ha llegado ({', '.join(f['futuras'][:5])}): "
                      "esta es la que rige hoy; comprueba si el artículo cambia.")
    if celex[5] == "L":
        avisos.append("Es una directiva: obliga a los Estados y no se aplica directamente entre particulares. Lo aplicable "
                      "en España es su transposición (búscala con buscar_ley); la directiva sirve para interpretarla y, si "
                      "no se transpuso bien, puede invocarse frente al Estado.")
    if con_apartado:
        avisos.append(f"Va el artículo {pedido} entero; busca en él el apartado o la letra.")
    if re.fullmatch(r"Art[íi]culo [^\n]{1,30}\n?[\u2014\u2013-]{3,}\s*", texto_):  # la raya de lo suprimido
        avisos.append("ATENCIÓN: el artículo figura como suprimido en esta versión.")
    return {"norma": celex, "titulo": f["titulo"], "articulo": lineas[inicio], "version": f["leida"],
            "version_de": de_cuando, "texto": recortar(texto_, max_caracteres), "fuente": _EURLEX + f["leida"],
            "fuente_doue": _EURLEX + celex, "avisos": avisos}


def _buscar_titulos(palabras: list[str], letras: str, max_resultados: int) -> list[dict]:
    consulta = (_P + "SELECT DISTINCT ?celex ?fecha ?vig ?titulo WHERE { ?w cdm:resource_legal_id_celex ?celex . "
                f'FILTER(REGEX(STR(?celex), "^3[0-9]{{4}}[{letras}][0-9]{{4}}$")) ?w cdm:work_date_document ?fecha . '
                f"?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language {_SPA} ; cdm:expression_title ?titulo . "
                + " ".join(f'FILTER(REGEX(?titulo, "{_patron(p)}", "i"))' for p in palabras)
                + " OPTIONAL { ?w cdm:resource_legal_in-force ?vig } "
                # Primero las vigentes y las normas 'madre': las que no modifican otra, reglamentos y directivas antes
                # que decisiones, y las de base antes que las de ejecución o delegadas (el RGPD antes que sus decisiones).
                "BIND(EXISTS { ?w cdm:resource_legal_amends_resource_legal ?z } AS ?modifica) "
                'BIND(SUBSTR(STR(?celex), 6, 1) = "D" AS ?decision) BIND(REGEX(?titulo, "de ejecuci|delegad", "i") AS ?derivada) '
                f"}} ORDER BY DESC(?vig) ?modifica ?decision ?derivada DESC(?fecha) LIMIT {tope(max_resultados, 25) + 6}")
    vistos, resultados = set(), []
    for f in _sparql(consulta):
        celex = f.get("celex", "")
        if not _CELEX.fullmatch(celex) or celex in vistos:
            continue
        vistos.add(celex)
        resultados.append({"celex": celex, "tipo": {"R": "reglamento", "L": "directiva", "D": "decisión"}[celex[5]],
                           "fecha": f.get("fecha", "")[:10], "titulo": " ".join(f.get("titulo", "").split())[:600],
                           "vigente": {"1": True, "0": False}.get(f.get("vig")), "fuente": _EURLEX + celex})
    return resultados


def buscar_norma_ue(texto: str, tipo: str = "todos", max_resultados: int = 10) -> dict:
    tipo = _sin_acentos((tipo or "todos").strip().lower())
    letras = "RLD" if tipo == "todos" else _TIPOS.get(tipo)
    if not letras:
        raise ValueError("tipo: reglamento, directiva, decision o todos.")
    palabras = _palabras(texto)
    resultados = _buscar_titulos(palabras, letras, max_resultados)
    parciales = None
    if not resultados and len(palabras) > 1:  # ninguno con todas (examen M05): las dos más largas, y luego la más larga
        for menos in (sorted(palabras, key=len, reverse=True)[:2], [max(palabras, key=len)]):
            if len(menos) < len(palabras) and (resultados := _buscar_titulos(menos, letras, max_resultados)):
                parciales = menos
                break
    hay_mas = len(resultados) > tope(max_resultados, 25)
    resultados = resultados[:tope(max_resultados, 25)]
    r = {"total": len(resultados), "resultados": resultados, "fuente": "https://eur-lex.europa.eu",
         "orden": "Primero las vigentes y las normas de base (las que no modifican otra; reglamentos y directivas antes "
                  "que decisiones y actos de ejecución); dentro de cada grupo, las más recientes.",
         "uso": "Artículo vigente: articulo_ue(celex, articulo). 'vigente' es lo que dice el repositorio de la UE "
                "(vacío si no lo dice)."}
    if hay_mas:
        r["aviso"] = "Hay más resultados que los mostrados ('total' es lo mostrado): acota con más palabras o con el tipo."
    if parciales:
        r["aviso"] = (f"Ningún título lleva todas esas palabras: estos llevan solo {', '.join(parciales)}. Comprueba que "
                      "es la norma que buscas (se busca en el título oficial en español).")
    if not resultados:
        r["aviso"] = ("Ningún título lleva esas palabras (se busca en el título oficial en español, que suele usar otras: "
                      "'protección de las personas físicas en lo que respecta al tratamiento de datos'). Prueba con otras "
                      "o con el número de la norma; si no, búscala en EUR-Lex y luego articulo_ue(celex, articulo).")
    return r


# Dónde interpreta una sentencia, como lo anota la Oficina de Publicaciones: 'A168LA' (artículo 168, letra a),
# 'A08BISTERP5' (artículo 8 bis ter, apartado 5) o '{AR|...fd_370/AR} 135 1.L' en las anotaciones antiguas.
_UBICACION = re.compile(rf"(?:A|\{{AR\|[^}}]{{0,120}}\}} ?)0*([0-9]{{1,4}})((?: ?(?:{_SUFIJOS.upper()}))*)")
_TRATADOS = {"E": ("2008", "2012", "2016"), "M": ("2008", "2012", "2016"), "P": ("2000", "2007", "2012", "2016")}


def _articulo_de(ubicacion: str) -> str | None:
    m = _UBICACION.match(ubicacion.upper())
    if not m:
        return None
    return f"{int(m.group(1))} {' '.join(re.findall(_SUFIJOS, m.group(2).lower()))}".strip()


def _en_titulo(titulo: str, celex: str, numero: int) -> bool:
    """Si las palabras clave del título ('Reglamento (UE) 2016/679', 'Artículo 5', 'Principios',
    'Artículos 24 y 82', separadas por rayas)
    nombran el artículo de esa norma: tras el segmento que cita la norma y hasta el que cita otra."""
    ano, num = int(celex[1:5]), int(celex[6:10])
    nuestra = re.compile(rf"\b(?:{ano}|{ano % 100:02d})/0*{num}\b|\b0*{num}/(?:{ano}|{ano % 100:02d})\b")
    activa = False
    for seg in re.split("[\u2014\u2013#]", titulo[:3000]):
        if nuestra.search(seg):
            activa = True
        elif re.search(r"\b(?:Directiva|Reglamento|Decisi[óo]n|Carta|TFUE|TUE|Tratado|Convenio)\b", seg):
            activa = False
        m = re.search(r"\bart[íi]culos? (.*)", seg, re.I) if activa else None
        estado = True  # tras 'apartado', 'letra'... los números no son artículos hasta la coma siguiente
        for tok in re.findall(r"[0-9]{1,4}|[^\W\d_]+|,", (m.group(1) if m else "").lower()):
            if tok == ",":
                estado = True
            elif tok.isdigit():
                if estado and int(tok) == numero:
                    return True
            elif tok not in ("y", "e", "artículo", "articulo", "artículos", "articulos") and tok not in _SUFIJOS.split("|"):
                estado = False
    return False


def jurisprudencia_ue_articulo(norma: str, articulo: str, max_resultados: int = 15) -> dict:
    celex = resolver(norma)
    pedido, apartado = _pedido(articulo)
    if celex.startswith("0"):  # una versión consolidada: la relación va a la norma de base
        celex = "3" + celex[1:10]
    numero = int(pedido.split()[0])
    tratado = celex.startswith("1")
    if tratado:  # cada artículo de los Tratados y de la Carta es una obra propia: '12008E267'
        if pedido != str(numero) or numero > 999:
            raise ValueError("En los Tratados y la Carta, indica el número del artículo ('267').")
        objetivo = " ".join(f'"1{a}{celex[5]}{numero:03d}"^^xsd:string' for a in _TRATADOS[celex[5]])
    else:
        objetivo = f'"{celex}"^^xsd:string'
    # Todas las que interpretan la norma (o el artículo, en los Tratados), con lo que tienen anotado: una petición.
    filas = _sparql(
        _P + "PREFIX ann: <http://publications.europa.eu/ontology/annotation#> SELECT ?celex ?ecli ?fecha "
        "(SAMPLE(?t) AS ?titulo) (GROUP_CONCAT(DISTINCT ?u; separator=\"|\") AS ?donde) WHERE { VALUES ?norma { "
        + objetivo + " } ?w cdm:resource_legal_id_celex ?norma . ?s cdm:case-law_interpretes_resource_legal ?w ; "
        "cdm:resource_legal_id_celex ?celex . OPTIONAL { ?a owl:annotatedSource ?s ; owl:annotatedTarget ?w ; "
        "owl:annotatedProperty cdm:case-law_interpretes_resource_legal ; ann:reference_to_modified_location ?u } "
        "OPTIONAL { ?s cdm:work_date_document ?fecha } OPTIONAL { ?s cdm:case-law_ecli ?ecli } OPTIONAL { ?e "
        f"cdm:expression_belongs_to_work ?s ; cdm:expression_uses_language {_SPA} ; cdm:expression_title ?t }} }} "
        "GROUP BY ?celex ?ecli ?fecha ORDER BY DESC(?fecha) LIMIT 480")
    vistos, resultados, sin_anotar = set(), [], 0
    for f in filas:
        c = f.get("celex", "")
        if not _CELEX_TJUE.fullmatch(c) or c in vistos:
            continue
        vistos.add(c)
        ubicaciones = [u for u in f.get("donde", "").split("|") if u]
        titulo = " ".join(f.get("titulo", "").split())
        sin_anotar += not ubicaciones
        if tratado or any(_articulo_de(u) == pedido for u in ubicaciones):
            por = "anotación"
        elif pedido == str(numero) and _en_titulo(titulo, celex, numero):
            por = "título"
        else:
            continue
        resultados.append({"celex": c, "ecli": f.get("ecli") or None, "fecha": f.get("fecha", "")[:10],
                           "tipo": {"J": "sentencia", "O": "auto", "C": "conclusiones"}[c[6]],
                           "titulo": titulo.replace("#", " · ")[:600], "segun": por,
                           **({"interpreta": ubicaciones[:10]} if ubicaciones else {}),
                           "fuente": "https://eur-lex.europa.eu/legal-content/ES/TXT/?uri=CELEX:" + c})
    r = {"norma": celex, "articulo": pedido, "total": len(resultados), "resultados": resultados[:tope(max_resultados, 50)],
         "fuente": "https://eur-lex.europa.eu",
         "nota": "Las resoluciones que el repositorio de la UE da como que interpretan ese artículo (lo que EUR-Lex "
                 "muestra como 'Interpreta'), las más recientes primero. 'segun': 'anotación' (la Oficina de "
                 "Publicaciones anota el artículo; 'interpreta': A = artículo, P = apartado, L = letra o párrafo) o "
                 "'título' (interpreta la norma sin artículo anotado, y las palabras clave de su título nombran el "
                 "artículo: menos seguro, compruébalo con leer_tjue). 'total' es un mínimo: la anotación de la Oficina de "
                 "Publicaciones no es exhaustiva (para más, buscar_tjue con 'artículo N' y la norma, o leer_tjue con "
                 "buscar_en='artículo N' en las que interpretan la norma). Las muy recientes pueden no estar aún. Para "
                 "leerlas: leer_tjue(celex, buscar_en=...)."}
    if not tratado:
        r["interpretan_la_norma"] = len(vistos)
    if len(filas) >= 480:
        r["aviso"] = ("La norma tiene tantas resoluciones que solo se han mirado las 480 más recientes: 'total' es un "
                      "mínimo.")
    if not resultados:
        r["aviso"] = (r.get("aviso", "") + " " + "Ninguna resolución consta como que interpreta ese artículo"
                      + (f" (sí {len(vistos)} la norma: búscalas con buscar_tjue)." if vistos and not tratado
                         else "; el repositorio de la UE no anota ninguna.")).strip()
    elif sin_anotar and not tratado:
        r["nota"] += (f" De las {len(vistos)} que interpretan la norma, {sin_anotar} no tienen artículo anotado; solo "
                      "se incluyen las que lo nombran en el título.")
    return r