# RemixZ Cleaner X v3.5.6

Paquete unificado (incluye todo lo de la línea 3.3).

## Incluye

- Limpieza de nombres y metadatos (RemixZ / Tio Dealer / WhatsApp)
- Barra de progreso gradient
- **ClubRemix DJ Tools** (renombrar membresía, TITLE, preview)
- Updater integrado (sin `UPDATE.exe`):
  - Configura repos al arrancar
  - Detecta updates vía `raw.githubusercontent.com` (+ API fallback)
  - **Anti-downgrade**: no aplica releases más viejos que la local
  - Descarga automática si el remoto es más nuevo

## Repos (mirror)

| Rol | URL |
|-----|-----|
| Principal | https://github.com/alikhan847547-sketch/remixz |
| Secundario (updates) | https://github.com/SMPROJECT115/newrepo |
| Mirror legacy | https://github.com/SMPROJECT115/remixz |

Al publicar con `push_to_github.ps1`, el contenido se sube a **todos** los mirrors (incluido `newrepo`).

## Ejecutar en local

```bat
python -u RemixZ_Cleaner_X_App.py
```

O doble clic en `RemixZ_Cleaner_X.exe` (build portable).

## Probar update local

1. Baja `version` en `version.json` a p.ej. `3.1.5`
2. Arranca la app → debe bajar solo el paquete más nuevo del repo
3. Con `3.5.6` y repo en `3.3.0` → **no** baja (anti-retroceso)

## Publicar (cuando esté OK en local)

```bat
powershell -ExecutionPolicy Bypass -File .\push_to_github.ps1
```

(Requiere `GITHUB_TOKEN` con acceso a los repos: principal + `SMPROJECT115/newrepo` + mirror legacy.)
