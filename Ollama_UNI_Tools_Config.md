# Ollama — Config operativa para las UNI Tools (Mac Studio)

> **Qué es esto.** Documenta cómo está configurado Ollama en el Mac Studio para
> servir a CBC, HRDD Helper y cualquier otra UNI Tool. Si quieres cambiar
> modelos preload, contexto, paralelismo, etc., esta guía es el manual.
>
> **Ámbito.** Todo lo de aquí es config del lado Ollama en esta máquina.
> Nada toca el código de CBC ni HRDD. Cambios que requieran tocar esas apps
> quedan marcados como **[Pendiente en el cliente]**.

---

## 1. Arquitectura instalada

```
~/Library/LaunchAgents/
├── com.ollama.server.plist         ← arranca "ollama serve" al login
└── com.ollama.preload.plist        ← lanza preload.sh al login

~/.ollama/
├── preload.conf                    ← LISTA EDITABLE de modelos permanentes
├── preload.sh                      ← script que lee la conf y los carga
└── logs/
    ├── server.log                  ← log nativo de Ollama (lo escribe la app)
    ├── launchd-server.log          ← stdout/stderr del ollama serve
    ├── launchd-preload.log         ← stdout/stderr del preload.sh
    └── preload.log                 ← log estructurado del preload.sh
```

**Lo que NO usamos:**

- La app GUI `/Applications/Ollama.app` (menu bar). Queda instalada pero sin
  auto-launch. Si la abres a mano, intentará levantar su propio `ollama serve`
  y competirá por el puerto 11434 — no lo hagas salvo para tarea puntual.
- El LaunchAgent bundled `com.ollama.ollama` (dentro de la app). Sólo lanza
  **Squirrel** (el auto-updater de Electron). No interfiere con nuestro serve,
  pero **tampoco actualiza el binario por sí solo** — ver sección 7.

---

## 2. Variables de entorno activas

Configuradas en `~/Library/LaunchAgents/com.ollama.server.plist`:

| Variable                    | Valor              | Efecto                                                                 |
|-----------------------------|--------------------|------------------------------------------------------------------------|
| `OLLAMA_HOST`               | `0.0.0.0:11434`    | Escucha en todas las interfaces (accesible desde Docker y Tailscale).  |
| `OLLAMA_NUM_PARALLEL`       | `2`                | Hasta 2 requests simultáneos por modelo cargado. Ver sección 8.        |
| `OLLAMA_MAX_LOADED_MODELS`  | `6`                | Hasta 6 modelos residentes (2 permanentes embed/rerank + 4 slots on-demand). |
| `OLLAMA_FLASH_ATTENTION`    | `1`                | Flash Attention ON. Más rápido, menos memoria. Apple Silicon lo soporta. |

**Coexistencia con LM Studio.** El backend de CBC/HRDD puede apuntar a cualquiera
de los dos runtimes (Ollama en `:11434`, LM Studio en `:1234`). Ambos conviven
en la misma máquina. Con la config actual (Ollama sin preload de generativos),
pueden funcionar en paralelo para pruebas A/B sin colisionar en RAM.

### Cómo editarlas

1. `open -e ~/Library/LaunchAgents/com.ollama.server.plist`
2. Cambia el `<string>...</string>` correspondiente (deja el `<key>` intacto).
3. Recarga:
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.ollama.server
   ```
   `-k` fuerza kill + restart. Esto **descarga todos los modelos** y el preload
   los volverá a cargar (~90 segundos).
4. Verifica:
   ```bash
   ollama ps
   ps eww -p $(pgrep -f "ollama serve" | head -1) | tr ' ' '\n' | grep ^OLLAMA_
   ```

---

## 3. Lista de modelos permanentes — `~/.ollama/preload.conf`

Archivo de texto, una línea = un tag. Comentarios con `#`.

**Preload actual** (mantiene estos con `keep_alive=-1`, nunca descargan):

- `nomic-embed-text:latest`        → ~578 MB (embeddings RAG)
- `bona/bge-reranker-v2-m3:latest` → ~1.5 GB (rerank RAG)

**Total resident:** ~2 GB. El resto (~510 GB) queda disponible para:
- Modelos generativos que CBC/HRDD carguen on-demand (gemma4, qwen3.5, etc.)
- LM Studio corriendo en paralelo (para pruebas A/B del backend)
- Sistema macOS y otras apps

**Filosofía:** Ollama sólo mantiene residente lo que se usa en **cada** query
de RAG (embed + rerank). Los modelos generativos los pide CBC/HRDD cuando
los necesita. La primera request a un modelo generativo frío paga cold-load
(8-15s para 30B, 25-45s para qwen3.5:122b). Con `keep_alive` largo en la
request (ej. `"30m"`), el modelo queda caliente durante la sesión.

**Modelos generativos disponibles** (ver `ollama list`):

- `gemma4:26b`, `gemma4:31B`, `gemma4:latest`
- `qwen3.5:9b`, `qwen3.5:27b`, `qwen3.5:35b`, `qwen3.5:122b`

### Cómo cambiar la lista

1. Edita el archivo:
   ```bash
   open -e ~/.ollama/preload.conf
   ```
2. Añade, quita o comenta líneas. El formato exacto está documentado al
   principio del archivo.
3. Aplica sin reiniciar el servidor (sólo recarga modelos):
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.ollama.preload
   ```
   O corre el script directamente:
   ```bash
   ~/.ollama/preload.sh
   ```
4. Comprueba:
   ```bash
   ollama ps
   tail -f ~/.ollama/logs/preload.log
   ```

**Importante.** El preload **no descarga modelos** que estén fuera de la lista.
Si quitas `gemma4:26b` del preload, seguirá cargado hasta que hagas:
```bash
curl http://127.0.0.1:11434/api/generate -d '{"model":"gemma4:26b","keep_alive":0}'
```
o reinicies el servidor (`launchctl kickstart -k gui/$(id -u)/com.ollama.server`).

---

## 4. Ver los logs

Los LaunchAgents corren headless — **no** hay ventana de Terminal que se abra
sola. Para ver logs en vivo, abre cualquier Terminal y:

```bash
# Log nativo de Ollama (peticiones, errores, tiempos)
tail -f ~/.ollama/logs/server.log

# Stdout/stderr capturado por launchd (si Ollama crashea, aparece aquí)
tail -f ~/.ollama/logs/launchd-server.log

# Preload: qué modelos cargó y cuánto tardó
tail -f ~/.ollama/logs/preload.log
```

Ctrl-C para salir del tail.

---

## 5. Operaciones frecuentes

### Ver qué modelos están cargados

```bash
ollama ps
```

Columnas: nombre, tamaño en RAM, procesador (100% GPU = 100% en Apple Silicon
unified memory), ventana de contexto, tiempo restante (`Forever` = keep_alive -1).

### Comprobar que Ollama está arriba

```bash
curl -s http://127.0.0.1:11434/api/tags | head -c 120
```

Si responde con JSON, está bien.

### Reiniciar Ollama (conservando los modelos preload)

```bash
launchctl kickstart -k gui/$(id -u)/com.ollama.server
# esperar ~5s a que levante
launchctl kickstart gui/$(id -u)/com.ollama.preload
```

### Parar Ollama por completo (ej. para mantenimiento)

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ollama.server.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ollama.preload.plist
```

Para volver a activarlo:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ollama.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ollama.preload.plist
```

### Forzar descarga de un modelo específico

```bash
curl -s http://127.0.0.1:11434/api/generate \
  -d '{"model":"qwen3.5:122b","keep_alive":0}'
```

### Lanzar un modelo puntual sin preload

```bash
ollama run qwen3.5:27b "prompt"
```

Esto usa las env vars del LaunchAgent (NUM_PARALLEL=4, etc.) porque el CLI
habla con el server vía HTTP — no arranca otro proceso.

---

## 6. Reboot del Mac

Flujo automático, sin intervención:

1. macOS arranca → login de Daniel.
2. `com.ollama.server` se carga → `ollama serve` en `0.0.0.0:11434` con env vars.
3. `com.ollama.preload` se carga en paralelo → `preload.sh` espera hasta 180s a
   que el server escuche, después carga los 6 modelos de `preload.conf` con
   `keep_alive=-1`.
4. En ~90-120s post-login, todos los modelos permanentes están residentes.

Si Ollama crashea en runtime, `KeepAlive=true` en el plist lo relanza de
inmediato. **Pero no recarga los modelos** — hay que relanzar preload:
```bash
launchctl kickstart gui/$(id -u)/com.ollama.preload
```

Esto **podría automatizarse** con un StartOnMount o un watchdog adicional, pero
de momento requiere intervención manual sólo si la app ha crasheado.

---

## 7. Actualizar Ollama

La app GUI tiene auto-updater (Squirrel), pero como no la usamos, las actualizaciones
vienen manuales:

### Opción A — descargar el .dmg nuevo

1. Descarga desde <https://ollama.com/download/mac>.
2. Reemplaza `/Applications/Ollama.app`.
3. Reinicia el servidor:
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.ollama.server
   launchctl kickstart gui/$(id -u)/com.ollama.preload
   ```

### Opción B — Homebrew (si lo tuvieras instalado así)

```bash
brew upgrade ollama
launchctl kickstart -k gui/$(id -u)/com.ollama.server
```

**Comprobar versión:**
```bash
ollama --version
```

---

## 8. NUM_PARALLEL — qué hace y cómo interactúa con num_ctx

`OLLAMA_NUM_PARALLEL=N` reserva **N slots** dentro de la ventana de contexto
del modelo cargado. Si CBC/HRDD cargan el modelo con `num_ctx=C`, entonces
**cada slot (= cada request paralelo) tiene `C/N` tokens efectivos**.

### Config actual

- `NUM_PARALLEL=2`
- `num_ctx` se fija **por request desde CBC/HRDD** (no en preload).

Para un modelo generativo cargado por CBC con `num_ctx=131072` (128k):
- 2 requests concurrentes posibles
- Cada request tiene 131072/2 = **65 536 tokens efectivos** (64k)

Para `num_ctx=262144` (256k):
- 2 concurrentes × 131 072 efectivos (128k cada uno)

### Por qué 2 y no 4

Con NUM_PARALLEL global y num_ctx alto, el KV cache pre-alocado por modelo
es grande. Bajar a 2 reduce a la mitad la memoria del KV cache y sigue
cubriendo el uso real esperado (2-3 sindicalistas concurrentes por frontend).
Si algún día aparece un caso con picos de 4+ usuarios simultáneos, se sube
a 4 tocando el plist.

### Cómo interactúa con el cold load

Como ya no preloadeamos generativos, la primera request define el `num_ctx`
del modelo para toda la vida de esa carga. Si la primera request es
`num_ctx=131072`, todas las siguientes deben usar ese valor; si piden
distinto, Ollama descarga y recarga (lento, cuidado).

**Recomendación para CBC/HRDD:** fijar un `num_ctx` consistente por modelo
en el llm_provider — todas las requests a `qwen3.5:35b` usan el mismo ctx,
todas a `qwen3.5:122b` otro, etc. Así se evitan recargas innecesarias.

### Cómo cambiar

Ver sección 2 ("Cómo editarlas"). Cualquier cambio en env vars requiere el
ciclo completo `bootout` + `bootstrap` del plist (no basta `kickstart -k`,
porque launchd cachea el plist original):

```bash
launchctl bootout gui/$(id -u)/com.ollama.server
launchctl bootout gui/$(id -u)/com.ollama.preload
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ollama.server.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ollama.preload.plist
```

---

## 9. Limitaciones conocidas y pendientes

### Think / reasoning desactivado — **[Pendiente en el cliente]**

Los modelos qwen3 (qwen3.5 family) tienen modo reasoning ("thinking") que
retrasa la primera respuesta porque emiten tokens `<think>...</think>` antes
de la respuesta útil.

**Desde Ollama no se puede desactivar permanentemente:**
- `PARAMETER think false` no existe en Modelfile (Ollama no lo soporta).
- `SYSTEM "/no_think"` en Modelfile queda sobrescrito por el system prompt
  de CBC/HRDD.
- Pasar `"think": false` en el body del request SÍ funciona — pero es lado
  cliente.

**Acción pendiente en próximo sprint de CBC/HRDD:** modificar `llm_provider.py`
para que todas las llamadas a modelos qwen3.* incluyan `"think": false` en el
body. Mientras tanto, los qwen3 piensan antes de responder (lento).

En el preload ya pasamos `think: false`, pero eso sólo afecta a la request de
warm-up — no persiste como setting del modelo.

### Context slots vs num_ctx

Ver sección 8. Config actual prioriza concurrencia (4 parallel) sobre
contexto efectivo por request (64k por slot). Si una de las apps empieza a
truncar CBAs largos, reconsiderar.

### Reload tras crash

Si el `ollama serve` crashea, `KeepAlive` lo relanza pero los modelos se pierden.
El preload NO se relanza solo en este escenario (sólo al login). Solución:
cuando notes degradación, manualmente `launchctl kickstart gui/501/com.ollama.preload`.

Mejora futura posible: WatchPaths o un LaunchAgent adicional que monitorice
`~/.ollama/logs/server.log` y relance el preload tras eventos de crash.

### Auto-updater deshabilitado de facto

Ver sección 7. Ollama no se actualiza solo. Chequea cada 1-2 meses.

---

## 10. Troubleshooting

### Ollama no responde

```bash
# 1. ¿Está el agent activo?
launchctl list | grep com.ollama.server

# 2. ¿Está el proceso vivo?
pgrep -lf "ollama serve"

# 3. Revisa logs
tail -100 ~/.ollama/logs/launchd-server.log
tail -100 ~/.ollama/logs/server.log

# 4. Forzar reinicio
launchctl kickstart -k gui/$(id -u)/com.ollama.server
sleep 3
launchctl kickstart gui/$(id -u)/com.ollama.preload
```

### El preload falló para un modelo

Mira `~/.ollama/logs/preload.log` — cada modelo que falla deja línea `FAIL`
con el error. Causas comunes:
- Tag mal escrito en `preload.conf` (compara con `ollama list`).
- Modelo no descargado: `ollama pull <tag>` y reintenta.
- RAM insuficiente: si `MAX_LOADED_MODELS` es menor que el número de
  permanentes, los últimos se descargan. Sube el límite.

### Conflicto de puerto 11434

```bash
lsof -iTCP:11434 -sTCP:LISTEN
```

Si ves dos procesos, alguien lanzó la GUI o un `ollama serve` a mano. Mata
el que no es el del LaunchAgent:
```bash
pkill -f "Ollama.app/Contents/Resources/ollama serve"
```

### Ver env vars actuales del server corriendo

```bash
ps eww -p $(pgrep -f "ollama serve" | head -1) | tr ' ' '\n' | grep ^OLLAMA_
```

---

## 11. Referencia — archivos y sus rutas

```
~/Library/LaunchAgents/com.ollama.server.plist
~/Library/LaunchAgents/com.ollama.preload.plist
~/.ollama/preload.conf
~/.ollama/preload.sh
~/.ollama/logs/server.log          ← log nativo Ollama
~/.ollama/logs/launchd-server.log  ← stdout/stderr serve
~/.ollama/logs/launchd-preload.log ← stdout/stderr preload
~/.ollama/logs/preload.log         ← log estructurado del preload
```

Binario Ollama: `/usr/local/bin/ollama` → symlink a `/Applications/Ollama.app/Contents/Resources/ollama`.

---

## 12. Histórico de la config

- **2026-04-23 (21:30)** — setup inicial. 6 modelos permanentes (4 generativos
  + embed + rerank), NUM_PARALLEL=4, MAX_LOADED_MODELS=8, FLASH_ATTENTION=1,
  HOST=0.0.0.0. Preload con num_ctx=262144.
- **2026-04-23 (22:37)** — simplificación tras análisis de memoria y comparativa
  con LM Studio. Preload reducido a embed + rerank únicamente (~2 GB residentes);
  generativos on-demand con num_ctx y keep_alive pasados por CBC/HRDD.
  NUM_PARALLEL bajado a 2, MAX_LOADED_MODELS bajado a 6. Libera ~220 GB de RAM
  para coexistir con LM Studio en paralelo durante fase de pruebas A/B del backend.
  Pendiente en cliente: disable think para qwen3.*, fijar num_ctx consistente por modelo.
