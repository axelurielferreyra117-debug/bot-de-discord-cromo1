import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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
            creado_por INTEGER NOT NULL
        )
        """
    )
    return conn


def crear_cromo(nombre: str, imagen_url: str, creado_por: int) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO cromos (nombre, imagen_url, owner_id, creado_por) VALUES (?, ?, NULL, ?)",
        (nombre, imagen_url, creado_por),
    )
    conn.commit()
    cromo_id = cur.lastrowid
    conn.close()
    return cromo_id


def obtener_cromo(cromo_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT id, nombre, imagen_url, owner_id FROM cromos WHERE id = ?", (cromo_id,)
    ).fetchone()
    conn.close()
    return row


def asignar_cromo(cromo_id: int, user_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE cromos SET owner_id = ? WHERE id = ?", (user_id, cromo_id))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def quitar_dueno(cromo_id: int) -> bool:
    conn = get_db()
    cur = conn.execute("UPDATE cromos SET owner_id = NULL WHERE id = ?", (cromo_id,))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def inventario_de(user_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nombre, imagen_url FROM cromos WHERE owner_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def listar_todos():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nombre, owner_id FROM cromos ORDER BY id"
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


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Conectado como {bot.user} (rol de mod ID: {MOD_ROLE_ID})")


@bot.tree.command(name="crear_cromo", description="Crea un cromo único nuevo (solo mods)")
@app_commands.describe(nombre="Nombre del cromo", imagen="Imagen del cromo (archivo)")
async def crear_cromo_cmd(interaction: discord.Interaction, nombre: str, imagen: discord.Attachment):
    if not es_mod(interaction):
        await interaction.response.send_message(
            f"Solo miembros con el rol <@&{MOD_ROLE_ID}> pueden crear cromos.", ephemeral=True
        )
        return

    if not (imagen.content_type or "").startswith("image/"):
        await interaction.response.send_message("El archivo adjunto tiene que ser una imagen.", ephemeral=True)
        return

    cromo_id = crear_cromo(nombre, imagen.url, interaction.user.id)

    embed = discord.Embed(title=f"Cromo #{cromo_id}: {nombre}", description="Sin dueño todavía")
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

    _, nombre, imagen_url, owner_actual = cromo
    asignar_cromo(cromo_id, usuario.id)

    embed = discord.Embed(title=f"Cromo #{cromo_id}: {nombre}", description=f"Nuevo dueño: {usuario.mention}")
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
    for cromo_id, nombre, imagen_url in filas[:10]:
        e = discord.Embed(title=f"#{cromo_id} — {nombre}")
        e.set_thumbnail(url=imagen_url)
        embeds.append(e)

    extra = f"\n(mostrando los primeros 10 de {len(filas)})" if len(filas) > 10 else ""
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

    _, nombre, imagen_url, owner_id = cromo
    dueno = f"<@{owner_id}>" if owner_id else "Sin dueño"
    embed = discord.Embed(title=f"Cromo #{cromo_id}: {nombre}", description=f"Dueño: {dueno}")
    embed.set_image(url=imagen_url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="lista_cromos", description="Lista todos los cromos y sus dueños")
async def lista_cromos(interaction: discord.Interaction):
    filas = listar_todos()
    if not filas:
        await interaction.response.send_message("Todavía no hay cromos creados.")
        return

    lineas = []
    for cromo_id, nombre, owner_id in filas:
        dueno = f"<@{owner_id}>" if owner_id else "_libre_"
        lineas.append(f"#{cromo_id} — **{nombre}** — {dueno}")

    texto = "\n".join(lineas)
    if len(texto) > 3900:
        texto = texto[:3900] + "\n… (lista recortada)"

    await interaction.response.send_message("📋 **Todos los cromos**\n" + texto)


# ---------- Servidor HTTP mínimo (para que Render mantenga el servicio despierto) ----------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    bot.run(DISCORD_TOKEN)
