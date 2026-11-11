# Novedades del conector de fuentes oficiales

## 0.3.0 · noviembre de 2026
- **Dos versiones, un solo código:** la versión abierta (BOE, UE, Catastro, VIES, subvenciones y BORME del día) y la de
  Líder IA (todo).
- **`diagnostico`:** comprueba Python, la carpeta del plugin, las herramientas y las skills, el índice del BORME y qué
  fuentes responden, con una consulta de control por fuente que distingue «la web no responde» de «la web ha cambiado».
  Dice el siguiente paso en lenguaje llano.
- **Instalación con un solo texto** (`INSTALAR.md`), para Windows y Mac, sin ejecutables, con el aviso de privacidad.
- **Skill `fuentes-ayuda`:** diez ejemplos copiables por áreas. Nueva `FAQ.md`.
- `estado` y `diagnostico` indican la versión y quién hace el conector.

## 0.2.1
- Normas autonómicas: `buscar_ley` y `articulo_vigente` encuentran las consolidadas en el BOE por número y comunidad.
- Una norma pedida por su número que está derogada o sin texto consolidado sale igualmente, marcada y con la norma que la
  derogó.
- `leer_documento_oficial`: lee un PDF o una página del BOE o de un boletín oficial con el lector del conector.
- `verificar_escrito` entiende «del mismo texto legal», «de la misma ley» o «ibídem».
- `buscar_norma_ue`: si ningún título lleva todas las palabras, busca con las más significativas y lo dice.
- Regla nueva: no se instalan paquetes ni programas para consultar fuentes.
## 0.2.0
- Plugin de Claude Code que funciona en cualquier carpeta; los datos quedan aparte y se conservan al actualizar.
- `verificar_escrito`: «existe y está vigente» (o «existe», en doctrina): que la cita exista no quiere decir que diga lo
  que afirma el borrador.
