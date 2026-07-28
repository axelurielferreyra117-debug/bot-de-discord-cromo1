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
    return conn


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
from flask import Flask, jsonify, send_from_directory

web_app = Flask(__name__, static_folder="static", static_url_path="")


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
        SELECT owner_id, owner_username, COUNT(*) as cantidad
        FROM cromos
        WHERE owner_id IS NOT NULL
        GROUP BY owner_id
        ORDER BY cantidad DESC
        """
    ).fetchall()
    conn.close()
    return jsonify(
        [{"owner_id": r[0], "owner_username": r[1], "cantidad": r[2]} for r in rows]
    )


def run_web_server():
    web_app.run(host="0.0.0.0", port=PORT, use_reloader=False)


if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.run(DISCORD_TOKEN)
