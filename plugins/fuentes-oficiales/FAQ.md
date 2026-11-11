# Preguntas frecuentes · Fuentes oficiales (versión abierta)

Para cualquier duda de instalación, empieza por pedirle a Claude: «ejecuta el diagnóstico del conector». Dice qué falla
y el siguiente paso.

**«Python no se reconoce» o se abre la Microsoft Store.**
Falta Python 3.11 o posterior. Instálalo de https://www.python.org/downloads/ y marca «Add python.exe to PATH» (o desde
la Microsoft Store, botón Obtener). En Windows, el `python` que abre la tienda es un atajo, no Python. Cierra y abre
Claude Code. En Mac, el comando es `python3`: Claude lo ajusta en `.mcp.json` y `hooks/hooks.json`.

**Claude no ve las herramientas ni las skills del conector.**
Cierra Claude Code del todo (no basta con cerrar la conversación) y ábrelo. Comprueba que la carpeta está en
`.claude/skills/fuentes-oficiales` de tu usuario y que dentro está `.claude-plugin/plugin.json`. Si sigue igual, vuelve a pegar el
texto de `INSTALAR.md`.

**Una consulta tarda mucho.**
Es normal: de 5 a 60 segundos por consulta, porque se lee la web oficial en directo (el Tribunal Constitucional, la DGT
y los convenios son los más lentos). Las consultas van de una en una. Si pasa de 2 minutos, pide `estado`: dice qué
fuente no responde. Una fuente caída es «no se pudo comprobar», nunca «no consta».

**Una fuente falla de repente, aunque ayer iba.**
Pide `diagnostico`: separa «la web no responde» (espera y reintenta) de «la web ha cambiado y el conector ya no la
entiende» (hace falta una actualización). Mientras tanto, consulta esa
fuente en su web oficial.

**El plugin o sus datos están en OneDrive (u otra nube).**
La nube puede sincronizar y bloquear archivos mientras el conector los usa. Excluye `.claude` de la sincronización, o
instala el plugin en una carpeta de usuario fuera de ella. El `diagnostico` avisa si lo detecta.

**¿Qué ve Claude de lo que consulto?**
Lo que escribes y lo que devuelven las fuentes, como en cualquier conversación de Claude Code. No hay servidor de
Jurium: no recibe nada. Sin nombres ni DNI de clientes; `verificar_escrito` pasa el texto por Claude, así que pega solo
el fragmento con las citas y con huecos («[cliente]»).

**Claude intenta instalar algo (pip, un programa).**
No hace falta nada más que Python. Dile que no: si el conector no llega, que te dé el enlace oficial.
