# Bot de Cromos

Sistema de cromos coleccionables **únicos** (1 sola copia por cromo, con
imagen). Solo los miembros con un rol específico (por defecto **Mod**) pueden
crear cromos y asignarlos. Cada usuario tiene un inventario con los cromos
que le fueron asignados.

## Comandos

- `/crear_cromo nombre imagen` — crea un cromo nuevo subiendo una imagen (solo rol Mod). Queda "sin dueño".
- `/dar_cromo cromo_id usuario` — asigna (o transfiere) un cromo a un usuario (solo rol Mod).
- `/quitar_cromo cromo_id` — le quita el dueño a un cromo, vuelve a quedar libre (solo rol Mod).
- `/inventario [usuario]` — muestra los cromos que tiene un usuario (o los tuyos).
- `/cromo cromo_id` — muestra info y dueño de un cromo puntual.
- `/lista_cromos` — lista todos los cromos creados y quién es el dueño de cada uno.

## 1. Crear el bot en Discord

1. Andá a https://discord.com/developers/applications → **New Application**.
2. En **Bot**, creá el bot y copiá el **Token** (esto va en `DISCORD_TOKEN`).
3. Activá el intent **Server Members Intent** (necesario para resolver roles).
4. En **OAuth2 → URL Generator**, tildá el scope `bot` y `applications.commands`,
   con permisos mínimos: `Send Messages`, `Attach Files`, `Use Slash Commands`.
5. Invitá el bot a tu servidor con la URL generada.
6. En tu servidor, creá (o verificá que exista) el rol que va a tener el
   poder de dar cromos, y asignátelo a vos mismo.
7. Sacá el **ID del rol**: en Discord, activá el Modo Desarrollador
   (Configuración → Avanzado → Modo desarrollador), después click derecho
   sobre el rol en la lista de roles del servidor → **Copiar ID**.

## 2. Desplegar en Render (free tier)

1. Subí esta carpeta a un repo de GitHub.
2. En Render: **New → Web Service**, conectá el repo.
3. Configuración:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`
4. Variables de entorno (**Environment**):
   - `DISCORD_TOKEN` = el token del paso 2
   - `MOD_ROLE_ID` = el ID del rol que copiaste en el paso 7
5. Deploy.

### Importante sobre el free tier de Render

- El servicio se "duerme" tras 15 minutos sin tráfico HTTP. Este bot incluye
  un mini servidor HTTP (`/`) para recibir pings — configurá **UptimeRobot**
  (gratis) para pingear la URL pública del servicio cada 5-10 minutos.
- El disco del free tier **no es persistente entre deploys**: si redeployás,
  `cromos.db` se reinicia y perdés los cromos creados. Para un servidor chico
  suele ser aceptable mientras no redeployes seguido; si te importa que
  persista siempre, migrar a una base de datos externa (ej. Render Postgres
  free tier) es el siguiente paso.
- Las URLs de imágenes que da Discord al subir un archivo son estables
  mientras el mensaje original no se borre, pero en teoría pueden
  refrescarse con el tiempo. Si alguna imagen deja de cargar, basta con
  volver a subirla con `/crear_cromo`.
