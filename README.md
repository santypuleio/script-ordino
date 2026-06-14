# script-ordino

Automatización de Instagram con Selenium para **Ordino**: limpia seguidos (Parte 1) y prospección comercial (Parte 2).

## Requisitos

- Python 3.10+
- Google Chrome

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# Editá .env con tu usuario y contraseña de Instagram (no se sube a git)
```

Variables en `.env`:

- `INSTAGRAM_USERNAME` — usuario (ej. ordino.ar)
- `INSTAGRAM_PASSWORD` — contraseña
- `INSTAGRAM_ACCOUNT` — mismo usuario; usa perfil Chrome dedicado

La primera vez puede pedir captcha o 2FA en la ventana; después la sesión queda guardada.

## Comandos

Usá `python instagram_profile.py --help` para ver la lista completa.

### Parte 1 — Unfollow

| Comando | Qué hace |
|---------|----------|
| *(sin args)* | Lista quién no te sigue de vuelta |
| `--unfollow` | Deja de seguir a esas cuentas |

### Parte 2 — Individuales

| Comando | Qué hace |
|---------|----------|
| `--discover` | Busca prospects por hashtag |
| `--follow` | Sigue prospects pendientes en la base |
| `--message` / `--mensajes` | Envía DMs comerciales |
| `--retry-messages` | Reenvía solo a las 9 cuentas pendientes (lista fija; excluye quien ya recibió DM) |
| `--mark-sent` | Marca en la base como DM enviado (sin Chrome; corrige falsos fallos) |
| `--outreach-status` | Muestra el ledger (sin abrir Chrome) |

### Parte 2 — Fusiones (presets)

| Comando | Pipeline |
|---------|----------|
| **`--engage`** | follow + message |
| **`--outreach`** | discover + follow + message |
| **`--prospect`** | discover + follow |
| **`--daily`** | unfollow + discover + follow + message |

También podés combinar pasos a mano: `--discover --follow`, `--follow --message`, etc.

### Opciones

| Flag | Efecto |
|------|--------|
| `--dry-run` | Simula sin ejecutar acciones reales |
| `--confirm` | Pide escribir `SI` antes de actuar |
| `--help` | Muestra ayuda |

## Ejemplos

```bash
# Todo en uno (unfollow + outreach completo)
python instagram_profile.py --daily

# Solo seguir y mandar mensaje (sin unfollow ni discover)
python instagram_profile.py --engage

# Outreach sin limpiar seguidos
python instagram_profile.py --outreach

# Buscar y seguir, sin DM todavía
python instagram_profile.py --prospect

# Combinación custom
python instagram_profile.py --discover --follow --dry-run
```

Por defecto **no pide confirmación** y **cierra el navegador solo**. En fusiones con follow + message, espera 2 min entre ambos y manda hasta 10 DMs a quien siguió en esa corrida.

## Variables de entorno

### Parte 1

| Variable | Default | Descripción |
|----------|---------|-------------|
| `INSTAGRAM_USERNAME` | (auto) | Tu usuario de Instagram |
| `OUTPUT_FILE` | `no_te_siguen.txt` | Archivo de salida |
| `UNFOLLOW_DELAY` | `5` | Segundos entre unfollows |
| `UNFOLLOW_MAX` | `0` (sin límite) | Máximo unfollows por ejecución |

### Parte 2

| Variable | Default | Descripción |
|----------|---------|-------------|
| `OUTREACH_HASHTAGS` | retro, 3D, tiendas (ver script) | Hashtags separados por coma |
| `FOLLOW_MAX` | `25` | Máximo follows por ejecución |
| `FOLLOW_DELAY` | `10` | Segundos entre follows |
| `MESSAGE_MAX` | `10` | Máximo DMs por ejecución |
| `MESSAGE_DELAY` | `20` | Segundos entre DMs |
| `OUTREACH_MIN_SCORE` | `2` | Score mínimo de bio |
| `OUTREACH_MAX_FOLLOWERS` | `50000` | Excluir cuentas muy grandes |
| `DISCOVER_MAX_HASHTAGS` | `8` | Hashtags por corrida (no recorre los 23 de una) |
| `DISCOVER_MAX_NEW` | `50` | Máximo prospects nuevos por discover |
| `DISCOVER_BATCH_SIZE` | `12` | Perfiles por lote (API paralela, mucho más rápido) |
| `DISCOVER_HASHTAG_PAUSE` | `0.4` | Segundos entre hashtags |
| `OUTREACH_ARGENTINA_HASHTAGS_ONLY` | `1` | Solo hashtags con `argentina`, `buenosaires`, etc. (no `#retrogaming` global) |
| `OUTREACH_REQUIRE_ARGENTINA` | `0` | Validar bio/URL al abrir cada perfil (off por defecto; más lento y falla seguido) |
| `OUTREACH_ARGENTINA_STRICT` | `1` | Solo si `OUTREACH_REQUIRE_ARGENTINA=1` |
| `OUTREACH_FILTER_AR_POSTS` | `0` | Filtrar por ubicación/caption en cada post del hashtag |
| `MESSAGE_MIN_HOURS_AFTER_FOLLOW` | `0` | Horas mínimas desde el follow para DM |
| `DM_MODE` | `profile` | `profile`, `api`, `manual` o `ui` (ver sección Mensajes) |
| `MESSAGE_EXPORT_FILE` | `mensajes_pendientes.txt` | Salida de `--export-messages` |
| `MESSAGE_PAUSE_AFTER_FOLLOW` | `120` | Segundos de espera post-follow en fusiones |
| `RATE_LIMIT_PAUSE` | `90` | Pausa ante error 429/403 |
| `REQUIRE_CONFIRM` | `0` | `1` o `--confirm` para pedir SI antes de actuar |

El estado se guarda en `ordino_outreach.db` (SQLite, local).

## Tests

```bash
python -m unittest test_outreach.py
```

## Login y sesión guardada

Instagram suele mostrar **ordino.ar + botón Continuar** (no usuario/contraseña). Después de Continuar aparece **«¿Guardar tu información de inicio de sesión?»** (`/accounts/onetap/`): el script pulsa **Ahora no** y sigue (ya no reintenta Continuar en esa pantalla).

La sesión se guarda en:

`%LOCALAPPDATA%\Ordino\ChromeInstagram_<tu_cuenta>\`

**Si te pide login en cada corrida:**

1. Revisá que en `.env` esté `INSTAGRAM_ACCOUNT=ordino.ar` (misma cuenta que en Continuar).
2. **No** tengas `RESET_SESSION=1` ni `LOGOUT=1` en `.env` (borran el perfil cada vez).
3. **No** uses `SYNC_CHROME_PROFILE=1` salvo que sepas por qué (pisa cookies).
4. La primera vez: hacé clic vos en **Continuar** si el script no alcanza; al cerrar debe decir `Cookie sessionid guardada`.
5. No abras dos scripts a la vez (corrompe el perfil de Chrome).

Tras un login correcto deberías ver `Sesión activa (no hace falta login)` en la siguiente corrida.

## Mensajes (forma simple)

Por defecto el script abre el **perfil del prospect** y pulsa **Mensaje** (no abre el inbox entre mensajes; eso rompía la sesión tras el primer DM).

```bash
python instagram_profile.py --message
```

Reintento solo a las cuentas que fallaron en la última corrida (sin tocar el resto del ledger):

```bash
python instagram_profile.py --retry-messages
```

Otras cuentas explícitas: `python instagram_profile.py --retry-messages user1 user2`

Si Instagram envió los DMs pero el script mostró fallos (verificación antigua):

```bash
python instagram_profile.py --mark-sent
```

Nueva corrida (descubrir tiendas retro / 3D / gamer, seguir y mandar DM):

```bash
python instagram_profile.py --outreach
```

| Modo | Cómo |
|------|------|
| **profile** (default) | Botón Mensaje en perfil; cierra el chat y vuelve al inicio entre cada envío |
| **API** | `DM_MODE=api` — solo fetch (puede fallar si el inbox no carga) |
| **Manual** | `python instagram_profile.py --export-messages` → `mensajes_pendientes.txt` |
| **ui** | `DM_MODE=ui` — perfil + compose si el inbox funciona (no recomendado en lotes) |

Prueba rápida a tu otra cuenta:

```bash
python instagram_profile.py --test-dm santypuleio
```

Verificar si un perfil parece argentino (bio, `.com.ar`, +54, ciudad en IG):

```bash
python instagram_profile.py --check-argentina nombreusuario
```

Por defecto el foco Argentina viene solo de **hashtags argentinos** (`#emprendedoresargentina`, `#buenosaires`, etc.). **No** se valida cada perfil al entrar (evita lentitud y falsos rechazos).

Opcional en `.env`:
- `OUTREACH_REQUIRE_ARGENTINA=1` — vuelve a revisar bio/URL antes de guardar/seguir.
- `OUTREACH_FILTER_AR_POSTS=1` — filtra por ubicación/caption en cada post del hashtag.
- `OUTREACH_ARGENTINA_HASHTAGS_ONLY=0` + `OUTREACH_HASHTAGS=...` — lista custom de tags.

## Sesión / logout

```bash
python instagram_profile.py --logout
python instagram_profile.py --logout-all
```

## Aviso

Usá el script con moderación. Instagram puede limitar tu cuenta si hacés muchas acciones seguidas. No subas los límites por defecto sin entender el riesgo.
