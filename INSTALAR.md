# Instalar Fuentes oficiales (versión abierta) · versión 0.3.1

Se instala con un solo texto que pegas en Claude Code. No escribes nada técnico: Claude hace el trabajo y te pide, una
sola vez, cerrar y abrir Claude Code. Dura unos 5 minutos.

## Qué tienes que hacer
1. Abre **Claude Code** (la app de escritorio, pestaña Code; o el terminal). Vale cualquier carpeta de trabajo.
2. Arrastra a la conversación la carpeta que has recibido (o el `.zip`), o escribe su ruta.
3. Copia el texto de abajo (de «Pega desde aquí» a «hasta aquí»), pégalo y pulsa Intro.
4. Cuando Claude te pida reiniciar, cierra Claude Code, ábrelo y **pega el mismo texto otra vez**: sigue por donde se quedó.

## Qué ve Claude (privacidad)
- El conector corre en tu ordenador y consulta solo webs oficiales de una lista cerrada. No hay servidor de Jurium por
  medio: Jurium no recibe tus consultas.
- Claude (Anthropic) ve lo que le escribes y lo que devuelven las fuentes, como en cualquier conversación de Claude Code.
- Las consultas no llevan datos personales de clientes. El conector rechaza un DNI o un NIE; un nombre de persona no
  lo puede detectar.
- `verificar_escrito` no envía el texto a las fuentes, pero **pasa por Claude**: pega solo el fragmento con las citas,
  con huecos (`[cliente]`, `[importe]`).
- Lo que devuelve es informativo y lo revisa siempre una persona antes de usarlo.

--- Pega desde aquí ---

Instala en mi Claude Code el conector «fuentes-oficiales» (Fuentes oficiales de Jurium (versión abierta), versión 0.3.1). El paquete
está en: https://github.com/IA-Para-Despachos/conector-leyes-oficiales-ia. Hazlo tú con tus herramientas, paso a paso y sin pedirme que escriba nada técnico. Háblame en español
sencillo. Si algo falla, para y explícame qué hace falta.

Reglas: no instales paquetes ni programas (pip, winget, brew...); no ejecutes nada del paquete salvo lo que indico aquí;
no toques archivos míos salvo el CLAUDE.md del paso 7; no copies datos de clientes a ningún sitio. Si el plugin ya está
copiado (paso 2 hecho), salta al paso 5.

Antes de empezar, dime en cinco líneas qué vas a hacer y este aviso de privacidad, con tus palabras: el conector corre en
mi ordenador y consulta solo webs oficiales; Jurium no recibe nada; Claude ve lo que yo escriba y lo que devuelven las
fuentes; sin datos personales de clientes (el conector rechaza DNI y NIE, pero no detecta un nombre); `verificar_escrito`
pasa el texto por Claude, así que pego solo el fragmento con las citas y con huecos («[cliente]»); lo que devuelve es
informativo y lo revisa siempre una persona. Después sigue.

1. **Python.** Ejecuta `python --version` (en Mac, `python3 --version`). Hace falta la 3.11 o posterior. Si el comando no
   existe, abre la Microsoft Store (en Windows, `python` sin instalar es un atajo a la tienda, no Python) o da una versión
   menor, no instales nada. Dime: «Necesitas Python 3.11 o posterior. Bájalo de https://www.python.org/downloads/ y, en
   Windows, marca la casilla "Add python.exe to PATH" al instalar (también puedes instalarlo desde la Microsoft Store
   con el botón Obtener). Cuando termine, cierra y abre Claude Code y pega este mismo texto otra vez.» y termina ahí.
   Anota qué comando funcionó (`python` o `python3`).

2. **Colocar el plugin.** En https://github.com/IA-Para-Despachos/conector-leyes-oficiales-ia está la carpeta `plugins/fuentes-oficiales` (con `.claude-plugin/plugin.json` dentro).
   Si es un `.zip`, descomprímelo en una carpeta temporal nueva (en Windows, `Expand-Archive`; en Mac, `unzip`). Si es la
   dirección de un repositorio (https://...), descárgalo en una carpeta temporal nueva (`git clone` si hay git; si no, su
   zip). Si es una carpeta, úsala tal cual. Copia `plugins/fuentes-oficiales` entera a la carpeta `.claude/skills/fuentes-oficiales` de mi
   usuario (Windows: `%USERPROFILE%\.claude\skills\fuentes-oficiales`; Mac: `~/.claude/skills/fuentes-oficiales`); crea `.claude/skills`
   si no existe. Si ya hay una carpeta con ese nombre, es una versión anterior: dime cuál era (su plugin.json) y sustitúyela
   entera, sin mezclar archivos (mis datos están fuera de ella y se conservan). Comprueba que existen
   `.claude-plugin/plugin.json` y `conector/servidor.py` en el destino. Si la ruta de mi usuario está dentro de OneDrive
   u otra nube, avísame (lee FAQ.md, en esa carpeta).

3. **Comando de Python.** Abre `.mcp.json` y `hooks/hooks.json` de la copia: el campo `command` debe ser el comando que
   funcionó en el paso 1. Si no coincide, cámbialo en los dos.

4. **Reiniciar.** Pídeme cerrar Claude Code del todo y abrirlo, y que al volver pegue este mismo texto otra vez. Detén
   aquí el trabajo hasta entonces.

5. **Comprobar que carga.** Mira si tienes las herramientas `estado`, `diagnostico`, `articulo_vigente` y
   `verificar_escrito` del conector «fuentes-oficiales» y estas skills: `ordenanzas-municipales`, `fuentes-ayuda`, `jurium-recursos`. Si no están, dime que hay que cerrar Claude Code
   del todo y abrirlo, y que, si sigue igual, lea FAQ.md (en la carpeta del plugin). No instales nada.

6. **Diagnóstico.** Avísame de que tarda unos 30 segundos y llama a `diagnostico`. Cuéntame en lenguaje llano qué va bien,
   qué no y el siguiente paso que da la propia herramienta. Si dice que falla Python o el plugin, para ahí.

7. **Regla en mi CLAUDE.md.** Busca el `CLAUDE.md` de la carpeta donde estoy; si no hay, usa el de mi usuario
   (`~/.claude/CLAUDE.md`) y, si dudas, pregúntame cuál. Añade este bloque al final, tal cual, salvo que ya haya uno
   igual, sin tocar nada más, y enséñame el cambio:

```markdown
## Fuentes oficiales (conector de Jurium)
- Cuando la respuesta dependa de una norma o un artículo, una cita o un dato catastral, consúltalo con el conector
  `fuentes-oficiales` y cita la fuente oficial. Si no hay nada de eso en juego, no lo uses: cada consulta tarda de 5 a 60 s.
- Sin datos personales de clientes en las consultas. Lo que devuelve es informativo: lo revisa siempre una persona.
- `verificar_escrito`: pega solo el fragmento con las citas y con huecos («[cliente]»); el texto pasa por Claude.
- No instales paquetes ni programas (pip, .venv...) para consultar fuentes: si el conector no llega, dilo y da el
  enlace oficial.
- Si el conector falla o algo parece raro: herramienta `diagnostico`.
```

8. **Primer valor.** Hazme con el conector esta pregunta y enséñame la respuesta con su fuente y cuánto ha
   tardado: «¿Qué dice hoy el artículo 20 de la Ley del IVA sobre la exención del alquiler de vivienda?». Después
   termina con un resumen de cuatro líneas (qué ha quedado hecho, qué falta, si algo) y dame estas tres preguntas listas
   para copiar:
   - Fiscal: «¿Qué dice hoy el artículo 20.Uno.23 de la Ley del IVA? Dime desde cuándo rige esa redacción y qué normas la han modificado.»
   - Laboral: «¿Qué dice hoy el artículo 53 del Estatuto de los Trabajadores sobre el despido objetivo? Cita la fuente oficial.»
   - Mercantil: «¿Qué dice hoy el artículo 160 de la Ley de Sociedades de Capital sobre las competencias de la junta general?»

   Y recuérdame que la skill `fuentes-ayuda` ("qué puedo preguntar") tiene diez ejemplos más.

--- hasta aquí ---

## Si algo no sale
Mira `FAQ.md`, en la carpeta del plugin (Python no reconocido, herramientas que no cargan, OneDrive...). La herramienta
`diagnostico` (pídeselo a Claude) dice qué falla y el siguiente paso.

## Actualizar y desinstalar
- **Actualizar:** repite este mismo texto con la carpeta nueva: Claude sustituye la versión anterior entera. Tus datos
  están fuera de la carpeta del plugin y se conservan. Lo que cambia, en `NOVEDADES.md`.
- **Desinstalar:** borra `.claude/skills/fuentes-oficiales` de tu usuario. Los datos que guardó el conector (la copia de textos
  leídos) están en `.claude/plugins/data/fuentes-oficiales-skills-dir/`: borra
  también esa carpeta si no los quieres.
