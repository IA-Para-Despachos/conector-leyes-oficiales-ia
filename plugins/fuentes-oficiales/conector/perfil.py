# Fuentes oficiales (versión abierta) 0.3.0. Hecho por Jurium. Licencia MIT (LICENSE).
"""Perfil de esta copia del conector. En desarrollo, todo; empaquetar.py reescribe este archivo al generar un paquete.

- PERFIL: "premium" (todo) o "light" (la ley abierta: BOE, UE, Catastro, VIES, subvenciones y BORME del día).
- PAQUETE: True en lo que se reparte. Sin activación por equipo ni actualización con manifiesto firmado (ese trabajo
  está aparcado: licencia.py y actualizar.py no van en ningún paquete).
- ENLACE_*: marcadores que empaquetar.py sustituye; si siguen sin rellenar, no se muestran."""
PERFIL = "light"
PAQUETE = True
ENLACE_COMUNIDAD = "https://www.skool.com/ia-para-despachos-3662"
LIGHT = PERFIL == "light"


def creditos() -> str:
    """La línea de atribución de `estado` y `diagnostico` (nunca va en la salida de las herramientas jurídicas)."""
    enlace = "" if ENLACE_COMUNIDAD.startswith("{") else f" ({ENLACE_COMUNIDAD})"
    return f"Hecho por Jurium · Comunidad IA para Despachos{enlace}"
