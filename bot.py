import io
import json
import os
import sqlite3
import threading

import discord
from discord import app_commands
from discord.ext import commands

# ---------- Configuración desde variables de entorno ----------
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
MOD_ROLE_ID = int(os.environ["MOD_ROLE_ID"])
PORT = int(os.environ.get("PORT", 10000))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Muchachada574!")

# ---------- Base de datos (SQLite) ----------
DB_PATH = "cromos.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cromos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            imagen_url TEXT NOT NULL,
            owner_id INTEGER,
            creado_por INTEGER NOT NULL,
            nivel INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    try:
        conn.execute("ALTER TABLE cromos ADD COLUMN nivel INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cromos ADD COLUMN owner_username TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cromos ADD COLUMN imagen_nivel1 TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cromos ADD COLUMN imagen_nivel2 TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE cromos ADD COLUMN imagen_nivel3 TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute(
        "UPDATE cromos SET imagen_nivel1 = imagen_url WHERE imagen_nivel1 IS NULL"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS jugadores (nombre TEXT PRIMARY KEY, avatar_url TEXT)"
    )
    return conn


def upsert_jugador(nombre: str, avatar_url: str = None):
    if not nombre:
        return
    conn = get_db()
    existente = conn.execute("SELECT avatar_url FROM jugadores WHERE nombre = ?", (nombre,)).fetchone()
    if existente is None:
        conn.execute("INSERT INTO jugadores (nombre, avatar_url) VALUES (?, ?)", (nombre, avatar_url))
    elif avatar_url is not None:
        conn.execute("UPDATE jugadores SET avatar_url = ? WHERE nombre = ?", (avatar_url, nombre))
    conn.commit()
    conn.close()


def listar_jugadores():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT j.nombre, j.avatar_url, COUNT(c.id) as cantidad
        FROM jugadores j
        LEFT JOIN cromos c ON c.owner_username = j.nombre
        GROUP BY j.nombre
        ORDER BY cantidad DESC, j.nombre ASC
        """
    ).fetchall()
    conn.close()
    return rows


def cromos_de_jugador(nombre: str):
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, nombre, owner_id, owner_username, nivel, imagen_nivel1, imagen_nivel2, imagen_nivel3
        FROM cromos WHERE owner_username = ? ORDER BY id
        """,
        (nombre,),
    ).fetchall()
    conn.close()
    return rows


def get_config(clave: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_config(clave: str, valor: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO config (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, valor),
    )
    conn.commit()
    conn.close()


def crear_cromo(nombre: str, imagen_url: str, creado_por: int, owner_id: int, owner_username: str) -> int:
    conn = get_db()
    cur = conn.execute(
        """
        INSERT INTO cromos (nombre, imagen_url, owner_id, owner_username, creado_por, imagen_nivel1)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (nombre, imagen_url, owner_id, owner_username, creado_por, imagen_url),
    )
    conn.commit()
    cromo_id = cur.lastrowid
    conn.close()
    upsert_jugador(owner_username)
    return cromo_id


def obtener_cromo(cromo_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT id, nombre, imagen_url, owner_id, nivel FROM cromos WHERE id = ?", (cromo_id,)
    ).fetchone()
    conn.close()
    return row


def asignar_cromo(cromo_id: int, user_id: int, username: str) -> bool:
    conn = get_db()
    cur = conn.execute(
        "UPDATE cromos SET owner_id = ?, owner_username = ? WHERE id = ?", (user_id, username, cromo_id)
    )
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    upsert_jugador(username)
    return ok


def quitar_dueno(cromo_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE cromos SET owner_id = NULL, owner_username = NULL WHERE id = ?", (cromo_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def borrar_cromo(cromo_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("DELETE FROM cromos WHERE id = ?", (cromo_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def reemplazar_imagen(cromo_id: int, nueva_imagen_url: str):
    """Reemplaza la imagen del nivel ACTUAL de un cromo (por si el link viejo se rompió), sin cambiar el nivel."""
    conn = get_db()
    row = conn.execute("SELECT nivel FROM cromos WHERE id = ?", (cromo_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    nivel_actual = row[0]
    columna_nivel = f"imagen_nivel{nivel_actual}"
    conn.execute(
        f"UPDATE cromos SET imagen_url = ?, {columna_nivel} = ? WHERE id = ?",
        (nueva_imagen_url, nueva_imagen_url, cromo_id),
    )
    conn.commit()
    conn.close()
    return nivel_actual


def subir_nivel(cromo_id: int, nueva_imagen_url: str):
    """Sube el cromo un nivel (1->2 o 2->3) y le cambia la imagen. Devuelve el nuevo nivel, o None si no existe o ya está al máximo."""
    conn = get_db()
    row = conn.execute("SELECT nivel FROM cromos WHERE id = ?", (cromo_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    nivel_actual = row[0]
    if nivel_actual >= 3:
        conn.close()
        return None
    nuevo_nivel = nivel_actual + 1
    columna_nivel = f"imagen_nivel{nuevo_nivel}"
    conn.execute(
        f"UPDATE cromos SET nivel = ?, imagen_url = ?, {columna_nivel} = ? WHERE id = ?",
        (nuevo_nivel, nueva_imagen_url, nueva_imagen_url, cromo_id),
    )
    conn.commit()
    conn.close()
    return nuevo_nivel


def contar_inventario(user_id: int) -> int:
    conn = get_db()
    total = conn.execute(
        "SELECT COUNT(*) FROM cromos WHERE owner_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    return total


def inventario_de(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nombre, imagen_url, nivel FROM cromos WHERE owner_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def listar_todos():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nombre, owner_id, nivel FROM cromos ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


def candidatos_upgrade(minimo: int = 5):
    """Usuarios con al menos `minimo` cromos, ordenados de mayor a menor cantidad."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT owner_id, COUNT(*) as cantidad
        FROM cromos
        WHERE owner_id IS NOT NULL
        GROUP BY owner_id
        HAVING cantidad >= ?
        ORDER BY cantidad DESC
        """,
        (minimo,),
    ).fetchall()
    conn.close()
    return rows


def exportar_todo():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, nombre, imagen_url, owner_id, owner_username, creado_por, nivel,
               imagen_nivel1, imagen_nivel2, imagen_nivel3
        FROM cromos ORDER BY id
        """
    ).fetchall()
    conn.close()
    columnas = [
        "id", "nombre", "imagen_url", "owner_id", "owner_username", "creado_por",
        "nivel", "imagen_nivel1", "imagen_nivel2", "imagen_nivel3",
    ]
    return [dict(zip(columnas, row)) for row in rows]


def importar_todo(datos: list) -> int:
    conn = get_db()
    for c in datos:
        conn.execute(
            """
            INSERT OR REPLACE INTO cromos
                (id, nombre, imagen_url, owner_id, owner_username, creado_por, nivel,
                 imagen_nivel1, imagen_nivel2, imagen_nivel3)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                c["id"], c["nombre"], c["imagen_url"], c["owner_id"], c["owner_username"],
                c["creado_por"], c["nivel"], c["imagen_nivel1"], c["imagen_nivel2"], c["imagen_nivel3"],
            ),
        )
    conn.commit()
    conn.close()
    return len(datos)


# ---------- Bot de Discord ----------
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def es_mod(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(role.id == MOD_ROLE_ID for role in interaction.user.roles)


NIVELES = {1: "⚪ Normal", 2: "🟣 Especial", 3: "🟡 Muy Especial"}


def etiqueta_nivel(nivel: int) -> str:
    return NIVELES.get(nivel, f"Nivel {nivel}")


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Conectado como {bot.user} (rol de mod ID: {MOD_ROLE_ID})")


@bot.tree.command(name="crear_cromo", description="Crea un cromo único nuevo (solo mods)")
@app_commands.describe(
    nombre="Nombre del cromo",
    imagen="Imagen del cromo (archivo)",
    dueño="A quién le pertenece (opcional, default: vos mismo)",
)
async def crear_cromo_cmd(
    interaction: discord.Interaction,
    nombre: str,
    imagen: discord.Attachment,
    dueño: discord.Member = None,
):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden crear cromos.", ephemeral=True
        )
        return

    if not (imagen.content_type or "").startswith("image/"):
        await interaction.response.send_message("El archivo adjunto tiene que ser una imagen.", ephemeral=True)
        return

    propietario = dueño or interaction.user
    cromo_id = crear_cromo(nombre, imagen.url, interaction.user.id, propietario.id, propietario.display_name)

    embed = discord.Embed(
        title=f"Cromo #{cromo_id}: {nombre}",
        description=f"Dueño: {propietario.mention}\nNivel: {etiqueta_nivel(1)}",
    )
    embed.set_image(url=imagen.url)
    await interaction.response.send_message(content="✅ Cromo creado.", embed=embed)


@bot.tree.command(name="dar_cromo", description="Asigna un cromo a un usuario (solo mods)")
@app_commands.describe(cromo_id="ID del cromo", usuario="Usuario que recibe el cromo")
async def dar_cromo(interaction: discord.Interaction, cromo_id: int, usuario: discord.Member):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden dar cromos.", ephemeral=True
        )
        return

    cromo = obtener_cromo(cromo_id)
    if cromo is None:
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    _, nombre, imagen_url, owner_actual, nivel = cromo
    asignar_cromo(cromo_id, usuario.id, usuario.display_name)

    embed = discord.Embed(
        title=f"Cromo #{cromo_id}: {nombre}",
        description=f"Nuevo dueño: {usuario.mention}\nNivel: {etiqueta_nivel(nivel)}",
    )
    embed.set_image(url=imagen_url)
    aviso_extra = f" (antes era de <@{owner_actual}>)" if owner_actual else ""
    await interaction.response.send_message(
        content=f"🎁 {usuario.mention} recibió el cromo **{nombre}**{aviso_extra}.", embed=embed
    )


@bot.tree.command(name="quitar_cromo", description="Le quita el dueño a un cromo, queda libre (solo mods)")
@app_commands.describe(cromo_id="ID del cromo")
async def quitar_cromo(interaction: discord.Interaction, cromo_id: int):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden quitar cromos.", ephemeral=True
        )
        return

    if not quitar_dueno(cromo_id):
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    await interaction.response.send_message(f"El cromo #{cromo_id} quedó sin dueño.")


@bot.tree.command(name="borrar_cromo", description="Borra un cromo para siempre, incluida su imagen y niveles (solo mods)")
@app_commands.describe(cromo_id="ID del cromo a borrar")
async def borrar_cromo_cmd(interaction: discord.Interaction, cromo_id: int):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden borrar cromos.", ephemeral=True
        )
        return

    cromo = obtener_cromo(cromo_id)
    if cromo is None:
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    _, nombre, _, _, _ = cromo
    borrar_cromo(cromo_id)
    await interaction.response.send_message(f"🗑️ Se borró el cromo #{cromo_id} (**{nombre}**) para siempre.")


@bot.tree.command(name="reemplazar_imagen", description="Reemplaza la imagen de un cromo si el link se rompió, sin cambiar su nivel (solo mods)")
@app_commands.describe(cromo_id="ID del cromo con la imagen rota", imagen="Imagen nueva para reemplazar")
async def reemplazar_imagen_cmd(interaction: discord.Interaction, cromo_id: int, imagen: discord.Attachment):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden hacer esto.", ephemeral=True
        )
        return

    cromo = obtener_cromo(cromo_id)
    if cromo is None:
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    if not (imagen.content_type or "").startswith("image/"):
        await interaction.response.send_message("El archivo adjunto tiene que ser una imagen.", ephemeral=True)
        return

    _, nombre, _, owner_id, nivel = cromo
    reemplazar_imagen(cromo_id, imagen.url)

    embed = discord.Embed(
        title=f"Cromo #{cromo_id}: {nombre}",
        description=f"Dueño: <@{owner_id}>\nNivel: {etiqueta_nivel(nivel)} (imagen reemplazada)",
    )
    embed.set_image(url=imagen.url)
    await interaction.response.send_message(content="🔧 Imagen reemplazada.", embed=embed)


@bot.tree.command(name="subir_nivel", description="Sube de nivel un cromo, cambiándole la imagen por un GIF (solo mods)")
@app_commands.describe(cromo_id="ID del cromo a subir de nivel", imagen="Nueva imagen/GIF para el nivel siguiente")
async def subir_nivel_cmd(interaction: discord.Interaction, cromo_id: int, imagen: discord.Attachment):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden subir de nivel un cromo.", ephemeral=True
        )
        return

    cromo = obtener_cromo(cromo_id)
    if cromo is None:
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    _, nombre, _, owner_id, nivel_actual = cromo

    if nivel_actual >= 3:
        await interaction.response.send_message(
            f"El cromo #{cromo_id} ya está en el nivel máximo ({etiqueta_nivel(3)}).", ephemeral=True
        )
        return

    if not (imagen.content_type or "").startswith("image/"):
        await interaction.response.send_message("El archivo adjunto tiene que ser una imagen o GIF.", ephemeral=True)
        return

    nuevo_nivel = subir_nivel(cromo_id, imagen.url)

    embed = discord.Embed(
        title=f"Cromo #{cromo_id}: {nombre}",
        description=f"Dueño: <@{owner_id}>\nNivel: {etiqueta_nivel(nuevo_nivel)} (antes: {etiqueta_nivel(nivel_actual)})",
    )
    embed.set_image(url=imagen.url)
    await interaction.response.send_message(
        content=f"⬆️ **{nombre}** subió a {etiqueta_nivel(nuevo_nivel)}!", embed=embed
    )


@bot.tree.command(name="candidatos", description="Lista usuarios con 5+ cromos, habilitados para subir de nivel uno (solo mods)")
async def candidatos_cmd(interaction: discord.Interaction):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden ver esto.", ephemeral=True
        )
        return

    filas = candidatos_upgrade(5)
    if not filas:
        await interaction.response.send_message("Todavía nadie llegó a 5 cromos.")
        return

    lineas = [f"<@{user_id}> — **{cantidad}** cromos" for user_id, cantidad in filas]
    await interaction.response.send_message("🌟 **Habilitados para subir de nivel un cromo**\n" + "\n".join(lineas))


@bot.tree.command(name="exportar_cromos", description="Descarga un respaldo de todos los cromos en un archivo (solo mods)")
async def exportar_cromos_cmd(interaction: discord.Interaction):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden exportar.", ephemeral=True
        )
        return

    datos = exportar_todo()
    contenido = json.dumps(datos, ensure_ascii=False, indent=2)
    archivo = discord.File(io.BytesIO(contenido.encode("utf-8")), filename="respaldo_cromos.json")
    await interaction.response.send_message(
        content=f"📦 Respaldo con **{len(datos)}** cromo(s). Guardá este archivo — con `/importar_cromos` lo restaurás.",
        file=archivo,
    )


@bot.tree.command(name="importar_cromos", description="Restaura los cromos desde un archivo de respaldo (solo mods)")
@app_commands.describe(archivo="El .json generado por /exportar_cromos")
async def importar_cromos_cmd(interaction: discord.Interaction, archivo: discord.Attachment):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden importar.", ephemeral=True
        )
        return

    try:
        contenido = await archivo.read()
        datos = json.loads(contenido.decode("utf-8"))
    except Exception:
        await interaction.response.send_message(
            "No pude leer ese archivo — asegurate de subir el .json generado por /exportar_cromos.",
            ephemeral=True,
        )
        return

    cantidad = importar_todo(datos)
    await interaction.response.send_message(f"✅ Se restauraron **{cantidad}** cromo(s) desde el respaldo.")


@bot.tree.command(name="inventario", description="Muestra el inventario de cromos de un usuario")
@app_commands.describe(usuario="Usuario a consultar (default: vos mismo)")
async def inventario(interaction: discord.Interaction, usuario: discord.Member = None):
    usuario = usuario or interaction.user
    filas = inventario_de(usuario.id)

    if not filas:
        await interaction.response.send_message(f"{usuario.mention} no tiene cromos todavía.")
        return

    # Discord permite hasta 10 embeds por mensaje
    embeds = []
    for cromo_id, nombre, imagen_url, nivel in filas[:10]:
        e = discord.Embed(title=f"#{cromo_id} — {nombre}", description=etiqueta_nivel(nivel))
        e.set_thumbnail(url=imagen_url)
        embeds.append(e)

    extra = f"\n(mostrando los primeros 10 de {len(filas)})" if len(filas) > 10 else ""
    if len(filas) >= 5:
        extra += "\n🌟 ¡Llegaste a 5+ cromos! Estás habilitado para subir de nivel uno."
    await interaction.response.send_message(
        content=f"🗂️ Inventario de {usuario.mention}: **{len(filas)}** cromo(s){extra}", embeds=embeds
    )


@bot.tree.command(name="cromo", description="Muestra info de un cromo por ID")
@app_commands.describe(cromo_id="ID del cromo")
async def cromo_info(interaction: discord.Interaction, cromo_id: int):
    cromo = obtener_cromo(cromo_id)
    if cromo is None:
        await interaction.response.send_message(f"No existe el cromo #{cromo_id}.", ephemeral=True)
        return

    _, nombre, imagen_url, owner_id, nivel = cromo
    dueno = f"<@{owner_id}>" if owner_id else "Sin dueño"
    embed = discord.Embed(
        title=f"Cromo #{cromo_id}: {nombre}", description=f"Dueño: {dueno}\nNivel: {etiqueta_nivel(nivel)}"
    )
    embed.set_image(url=imagen_url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="lista_cromos", description="Lista todos los cromos y sus dueños")
async def lista_cromos(interaction: discord.Interaction):
    filas = listar_todos()
    if not filas:
        await interaction.response.send_message("Todavía no hay cromos creados.")
        return

    lineas = []
    for cromo_id, nombre, owner_id, nivel in filas:
        dueno = f"<@{owner_id}>" if owner_id else "_libre_"
        lineas.append(f"#{cromo_id} — **{nombre}** ({etiqueta_nivel(nivel)}) — {dueno}")

    texto = "\n".join(lineas)
    if len(texto) > 3900:
        texto = texto[:3900] + "\n… (lista recortada)"

    await interaction.response.send_message("📋 **Todos los cromos**\n" + texto)


# ---------- Servidor web (Flask): sirve la página y la API, y mantiene Render despierto ----------
from flask import Flask, Response, jsonify, request, send_from_directory

web_app = Flask(__name__, static_folder="static", static_url_path="")
UPLOADS_DIR = os.path.join("static", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)


@web_app.route("/")
def index():
    return send_from_directory("static", "index.html")


@web_app.route("/api/cromos")
def api_cromos():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, nombre, owner_id, owner_username, nivel,
               imagen_nivel1, imagen_nivel2, imagen_nivel3
        FROM cromos ORDER BY id
        """
    ).fetchall()
    conn.close()

    resultado = []
    for cid, nombre, owner_id, owner_username, nivel, i1, i2, i3 in rows:
        resultado.append(
            {
                "id": cid,
                "nombre": nombre,
                "nivel_actual": nivel,
                "owner_id": owner_id,
                "owner_username": owner_username,
                "imagenes": {"1": i1, "2": i2, "3": i3},
            }
        )
    return jsonify(resultado)


@web_app.route("/api/ranking")
def api_ranking():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT owner_username, COUNT(*) as cantidad
        FROM cromos
        WHERE owner_username IS NOT NULL AND owner_username != ''
        GROUP BY owner_username
        ORDER BY cantidad DESC
        """
    ).fetchall()
    conn.close()
    return jsonify(
        [{"owner_username": r[0], "cantidad": r[1]} for r in rows]
    )



REGLAS_DEFAULT = """
<h3>Cómo se consiguen los cromos</h3>
<p>Para conseguir tu primer cromo, tenés que retar a <strong>Silver</strong> de alguna de estas formas:</p>
<ul>
  <li>Retarlo a una apuesta de anime (uno que <strong>ninguno de los dos</strong> haya visto).</li>
  <li>Donar 10 USD en YouTube.</li>
  <li>Retarlo a un juego.</li>
  <li>Poner tu corona en juego, si sos el <strong>Top 1</strong> → a cambio recibís 2 personajes.</li>
</ul>
<h3>Niveles</h3>
<ul>
  <li><strong>Normal</strong> — el nivel con el que nace todo cromo.</li>
  <li><strong>Especial</strong> — una versión mejorada, con efecto animado.</li>
  <li><strong>Muy Especial</strong> — la versión máxima, con el personaje en movimiento completo.</li>
</ul>
<p>Al llegar a <strong>5 cromos</strong> en tu colección, quedás habilitado para que el mod suba de nivel a uno de los tuyos. No perdés ningún cromo por esto.</p>
<h3>Enfrentamientos entre jugadores</h3>
<p>Una vez que ya tenés un cromo (ganado contra Silver), se te habilitan las apuestas contra el resto de la muchachada.</p>
<ul>
  <li>Si querés el personaje de otro jugador, lo podés retar.</li>
  <li>Él tiene derecho a rechazar la apuesta — en ese caso, ambos se quedan con lo suyo.</li>
  <li>Si ambos aceptan, cada uno pone su cromo en juego.</li>
  <li>El ganador se lleva los dos cromos, el perdedor se queda sin el suyo.</li>
</ul>
<h3>Prohibiciones</h3>
<p>Está terminantemente prohibido robar o reclamar un cromo que no te pertenece (o intentarlo).</p>
<p><strong>Consecuencias:</strong></p>
<ul>
  <li>Se te confisca todo el inventario.</li>
  <li>Quedás inhabilitado para apostar por 3 meses.</li>
</ul>
<h3>Cosas a tener en cuenta</h3>
<ul>
  <li>Si perdés contra Silver, no podés volver a apostar por 3 meses.</li>
  <li>Si perdés una apuesta contra otro jugador, perdés tu cromo.</li>
  <li>Robar tiene la misma sanción: confiscación total + 3 meses sin apostar.</li>
</ul>
"""


@web_app.route("/api/config")
def api_config():
    reglas = get_config("reglas", REGLAS_DEFAULT)
    links = get_config("links", '{"youtube":"","discord":"","twitter":""}')
    return jsonify({"reglas": reglas, "links": json.loads(links)})


def _password_valida(pw: str) -> bool:
    return pw == ADMIN_PASSWORD


@web_app.route("/api/admin/verificar", methods=["POST"])
def api_admin_verificar():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify({"ok": _password_valida(data.get("password", ""))})


@web_app.route("/api/admin/reglas", methods=["POST"])
def api_admin_reglas():
    data = request.get_json(force=True, silent=True) or {}
    if not _password_valida(data.get("password", "")):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403
    set_config("reglas", data.get("contenido", ""))
    return jsonify({"ok": True})


@web_app.route("/api/admin/links", methods=["POST"])
def api_admin_links():
    data = request.get_json(force=True, silent=True) or {}
    if not _password_valida(data.get("password", "")):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403
    links = {
        "youtube": data.get("youtube", ""),
        "discord": data.get("discord", ""),
        "twitter": data.get("twitter", ""),
    }
    set_config("links", json.dumps(links))
    return jsonify({"ok": True})


@web_app.route("/api/admin/reemplazar_imagen", methods=["POST"])
def api_admin_reemplazar_imagen():
    password = request.form.get("password", "")
    if not _password_valida(password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    cromo_id = request.form.get("cromo_id", type=int)
    archivo = request.files.get("imagen")
    if not cromo_id or not archivo:
        return jsonify({"ok": False, "error": "Faltan datos"}), 400

    nombre_archivo = f"cromo{cromo_id}_{int(threading.get_ident())}_{archivo.filename}"
    ruta_local = os.path.join(UPLOADS_DIR, nombre_archivo)
    archivo.save(ruta_local)
    url_publica = f"/uploads/{nombre_archivo}"

    resultado = reemplazar_imagen(cromo_id, url_publica)
    if resultado is None:
        return jsonify({"ok": False, "error": "No existe ese cromo"}), 404

    return jsonify({"ok": True, "imagen_url": url_publica})


@web_app.route("/api/jugadores")
def api_jugadores():
    filas = listar_jugadores()
    return jsonify([{"nombre": n, "avatar_url": a, "cantidad": c} for n, a, c in filas])


@web_app.route("/api/jugadores/<nombre>/cromos")
def api_jugador_cromos(nombre):
    rows = cromos_de_jugador(nombre)
    resultado = []
    for cid, cnombre, owner_id, owner_username, nivel, i1, i2, i3 in rows:
        resultado.append(
            {
                "id": cid,
                "nombre": cnombre,
                "nivel_actual": nivel,
                "owner_id": owner_id,
                "owner_username": owner_username,
                "imagenes": {"1": i1, "2": i2, "3": i3},
            }
        )
    return jsonify(resultado)


@web_app.route("/api/admin/crear_jugador", methods=["POST"])
def api_admin_crear_jugador():
    password = request.form.get("password", "")
    if not _password_valida(password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    nombre = (request.form.get("nombre") or "").strip()
    if not nombre:
        return jsonify({"ok": False, "error": "Falta el nombre"}), 400

    avatar_url = None
    archivo = request.files.get("avatar")
    if archivo and archivo.filename:
        nombre_archivo = f"avatar_{nombre}_{int(threading.get_ident())}_{archivo.filename}"
        archivo.save(os.path.join(UPLOADS_DIR, nombre_archivo))
        avatar_url = f"/uploads/{nombre_archivo}"

    upsert_jugador(nombre, avatar_url)
    return jsonify({"ok": True})


@web_app.route("/api/admin/crear_cromo", methods=["POST"])
def api_admin_crear_cromo():
    password = request.form.get("password", "")
    if not _password_valida(password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    nombre = (request.form.get("nombre") or "").strip()
    dueno = (request.form.get("dueno") or "").strip()
    archivo = request.files.get("imagen")
    if not nombre or not archivo:
        return jsonify({"ok": False, "error": "Falta el nombre o la imagen"}), 400

    nombre_archivo = f"nuevo_{int(threading.get_ident())}_{archivo.filename}"
    archivo.save(os.path.join(UPLOADS_DIR, nombre_archivo))
    url_publica = f"/uploads/{nombre_archivo}"

    cromo_id = crear_cromo(nombre, url_publica, 0, None, dueno or None)
    return jsonify({"ok": True, "cromo_id": cromo_id})


@web_app.route("/api/admin/cambiar_dueno", methods=["POST"])
def api_admin_cambiar_dueno():
    data = request.get_json(force=True, silent=True) or {}
    if not _password_valida(data.get("password", "")):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    cromo_id = data.get("cromo_id")
    nuevo_dueno = (data.get("dueno") or "").strip()
    if not cromo_id:
        return jsonify({"ok": False, "error": "Falta el cromo"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE cromos SET owner_id = NULL, owner_username = ? WHERE id = ?",
        (nuevo_dueno or None, cromo_id),
    )
    conn.commit()
    conn.close()
    if nuevo_dueno:
        upsert_jugador(nuevo_dueno)
    return jsonify({"ok": True})


@web_app.route("/api/admin/exportar")
def api_admin_exportar():
    password = request.args.get("password", "")
    if not _password_valida(password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    datos = exportar_todo()
    contenido = json.dumps(datos, ensure_ascii=False, indent=2)
    return Response(
        contenido,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=respaldo_cromos.json"},
    )


@web_app.route("/api/admin/importar", methods=["POST"])
def api_admin_importar():
    password = request.form.get("password", "")
    if not _password_valida(password):
        return jsonify({"ok": False, "error": "Contraseña incorrecta"}), 403

    archivo = request.files.get("archivo")
    if not archivo:
        return jsonify({"ok": False, "error": "Falta el archivo"}), 400

    try:
        datos = json.loads(archivo.read().decode("utf-8"))
    except Exception:
        return jsonify({"ok": False, "error": "El archivo no es un respaldo válido"}), 400

    cantidad = importar_todo(datos)
    return jsonify({"ok": True, "cantidad": cantidad})


def run_web_server():
    web_app.run(host="0.0.0.0", port=PORT, use_reloader=False)


if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.run(DISCORD_TOKEN)
