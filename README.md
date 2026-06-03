# script-ordino

Automatización de Instagram con Selenium: detecta quién no te sigue de vuelta y opcionalmente deja de seguir esas cuentas.

## Requisitos

- Python 3.10+
- Google Chrome

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

```bash
# Listar quién sigues y no te sigue
python instagram_profile.py

# Simular unfollow
python instagram_profile.py --unfollow --dry-run

# Dejar de seguir a quienes no te siguen (sin límite por defecto)
python instagram_profile.py --unfollow

# Cerrar sesión / cambiar de cuenta
python instagram_profile.py --logout
python instagram_profile.py --logout-all
```

## Variables de entorno (opcional)

| Variable | Descripción |
|----------|-------------|
| `INSTAGRAM_USERNAME` | Tu usuario de Instagram |
| `OUTPUT_FILE` | Archivo de salida (default: `no_te_siguen.txt`) |
| `UNFOLLOW_DELAY` | Segundos entre cada unfollow (default: 5) |
| `UNFOLLOW_MAX` | Máximo por ejecución (default: 0 = sin límite) |

## Aviso

Usa el script con moderación. Instagram puede limitar tu cuenta si haces muchas acciones seguidas.
