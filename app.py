import streamlit as st
import sqlite3
import requests
import random
import time

# URL de tu API de Suno en Render Pro
RENDER_API_URL = "https://api-suno-nptk.onrender.com"

# 1. INICIALIZACIÓN DE LA BASE DE DATOS LOCAL (SQLite)
def init_db():
    conn = sqlite3.connect("jatune_production.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artistas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE,
            fecha_creacion TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS canciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artista_id INTEGER,
            titulo TEXT,
            genero TEXT,
            audio_url TEXT,
            estado TEXT,
            FOREIGN KEY (artista_id) REFERENCES artistas (id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# 2. ALGORITMO DE NOMBRE ARTÍSTICO ALEATORIO (Respaldo en caso de no usar la lista)
def generar_nombre_artistico():
    prefijos = ["Aether", "Zuki", "Lumo", "Vibe", "Nova", "Drako", "Neon", "Sintax", "Baty", "Yleg", "JMAR", "JJ"]
    nucleos = ["Pop", "Focus", "Chispero", "Tune", "Moon", "Studio", "Legacy", "Sonic", "Beat", "Wave"]
    sufijos = ["CXT", "Project", "Bass", "Mundo", "Loop", "Gold", "Session"]
    while True:
        if random.random() > 0.5:
            nombre = f"{random.choice(prefijos)} {random.choice(nucleos)}"
        else:
            nombre = f"{random.choice(prefijos)} {random.choice(nucleos)} {random.choice(sufijos)}"
        
        conn = sqlite3.connect("jatune_production.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM artistas WHERE nombre = ?", (nombre,))
        existe = cursor.fetchone()
        conn.close()
        if not existe:
            return nombre

# INTERFAZ VISUAL (Configuración del Layout de Streamlit)
st.set_page_config(page_title="JATune Production — Dashboard", layout="wide", initial_sidebar_state="expanded")

# Estilo personalizado Dark Mode Premium
st.markdown("""
    <style>
    .main { background-color: #0b0f19; color: #e5e7eb; }
    h1, h2, h3, h4 { font-family: 'Poppins', sans-serif; }
    .stButton>button { background: linear-gradient(135deg, #ec4899, #8b5cf6); color: white; border: none; padding: 12px 24px; border-radius: 8px; font-weight: bold; width: 100%; }
    .stButton>button:hover { background: linear-gradient(135deg, #8b5cf6, #ec4899); color: white; }
    </style>
    """, unsafe_style_with_html=True)

st.title("🎵 JATune Production")
st.caption("Consola Central de Automatización y Gestión de Catálogos")

# Pestañas principales de navegación (Agregamos la pestaña de "Administrar Roster")
tab_estudio, tab_inventario, tab_roster = st.tabs(["🚀 Módulo de Production", "📁 Catálogo e Historial", "⚙️ Administrar Roster"])

# --- TAB 1: MÓDULO DE PRODUCCIÓN ---
with tab_estudio:
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.subheader("🤖 Control de Identidad (Artista)")
        opcion_artista = st.radio(
            "Selecciona el destino del catálogo:",
            ["Elegir de mi Roster Guardado", "Crear Nuevo Artista Manual", "Generar Nombre Random (Algoritmo)"]
        )
        
        # Cargar artistas desde la base de datos
        conn = sqlite3.connect("jatune_production.db")
        cursor = conn.cursor()
        cursor.execute("SELECT nombre FROM artistas ORDER BY nombre ASC")
        artistas_guardados = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        artista_final = ""
        
        if opcion_artista == "Elegir de mi Roster Guardado":
            if artistas_guardados:
                artista_final = st.selectbox("Selecciona un artista de tu roster activo:", artistas_guardados)
            else:
                st.warning("⚠️ Tu roster está vacío. Ve a la pestaña 'Administrar Roster' para cargar tus 100 nombres de golpe.")
        
        elif opcion_artista == "Crear Nuevo Artista Manual":
            artista_final = st.text_input("Escribe el nombre del nuevo artista:").strip()
            
        elif opcion_artista == "Generar Nombre Random (Algoritmo)":
            if "nombre_random_actual" not in st.session_state:
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
            if st.button("🎲 Cambiar Nombre Aleatorio"):
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
            artista_final = st.session_state["nombre_random_actual"]
            st.info(f"Artista sugerido: **{artista_final}**")

    with col2:
        st.subheader("📝 Carga de Contenido Musical")
        modo_entrada = st.radio("Método de inyección:", ["Por Lote (Parámetros Fijos)", "Entrada Masiva (Pegar Bloque de Texto)"])
        
        lista_prompts = []
        if modo_entrada == "Por Lote (Parámetros Fijos)":
            cantidad = st.number_input("¿Cuántas canciones generar para este lote?", min_value=1, max_value=20, value=1)
            genero_fijo = st.text_input("Ingresa el estilo/género:")
            if genero_fijo:
                lista_prompts = [genero_fijo] * int(cantidad)
        elif modo_entrada == "Entrada Masiva (Pegar Bloque de Texto)":
            bloque_texto = st.text_area("Pega la lista de pistas (Una por línea):", height=150)
            if bloque_texto:
                lista_prompts = [line.strip() for line in bloque_texto.split("\n") if line.strip()]

    st.markdown("---")
    
    if st.button("Lanzar Secuencia Automática a Render Pro ⚡"):
        if not artista_final:
            st.error("Error: Debes definir una identidad de artista válida.")
        elif not lista_prompts:
            st.error("Error: No has ingresado ningún género o prompt.")
        else:
            progreso_status = st.empty()
            with st.spinner(f"Procesando música para **{artista_final}**..."):
                conn = sqlite3.connect("jatune_production.db")
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO artistas (nombre, fecha_creacion) VALUES (?, ?)", (artista_final, time.strftime("%Y-%m-%d")))
                cursor.execute("SELECT id FROM artistas WHERE nombre = ?", (artista_final,))
                artista_id = cursor.fetchone()[0]
                
                exitos, fallos = 0, 0
                for idx, prompt_musical in enumerate(lista_prompts):
                    progreso_status.info(f"⏳ Generando pista {idx+1}/{len(lista_prompts)}: *{prompt_musical}*...")
                    try:
                        payload = {"prompt": prompt_musical, "make_instrumental": True, "wait_audio": True}
                        response = requests.post(f"{RENDER_API_URL}/api/generate", json=payload, timeout=300)
                        if response.status_code == 200:
                            data = response.json()
                            tracks = data.get("tracks", [{"title": f"Track {idx+1}", "audio_url": ""}])
                            for track in tracks:
                                cursor.execute("""
                                    INSERT INTO canciones (artista_id, titulo, genero, audio_url, estado)
                                    VALUES (?, ?, ?, ?, ?)
                                """, (artista_id, track.get("title"), prompt_musical, track.get("audio_url"), "Listo"))
                            exitos += 1
                        else:
                            fallos += 1
                    except Exception as e:
                        fallos += 1
                conn.commit()
                conn.close()
                progreso_status.empty()
                st.success(f"¡Lote terminado! Éxitos: {exitos} | Fallos: {fallos}")
                st.balloons()

# --- TAB 2: CATÁLOGO ---
with tab_inventario:
    st.subheader("📁 Inventario Global de JATune Production")
    conn = sqlite3.connect("jatune_production.db")
    cursor = conn.cursor()
    cursor.execute("SELECT a.nombre, COUNT(c.id), a.id FROM artistas a LEFT JOIN canciones c ON a.id = c.artista_id GROUP BY a.id ORDER BY COUNT(c.id) DESC")
    res_artistas = cursor.fetchall()
    
    if res_artistas:
        col_inv1, col_inv2 = st.columns([1, 2])
        with col_inv1:
            st.markdown("### Resumen de Roster")
            for name, count, _ in res_artistas:
                st.metric(label=f"Artista: {name}", value=f"{count} tracks")
        with col_inv2:
            st.markdown("### Historial de Masters")
            artista_filtro = st.selectbox("Selecciona un perfil para auditar:", [row[0] for row in res_artistas])
            if artista_filtro:
                cursor.execute("SELECT c.titulo, c.genero, c.audio_url, c.estado FROM canciones c JOIN artistas a ON c.artista_id = a.id WHERE a.nombre = ? ORDER BY c.id DESC", (artista_filtro,))
                for titulo, genero, url, estado in cursor.fetchall():
                    st.write(f"🎵 **{titulo}** — *{genero}* (Estado: {estado})")
                    if url: st.audio(url)
                    st.markdown("---")
    else:
        st.info("Catálogo limpio por el momento.")
    conn.close()

# --- TAB 3: NUEVA PESTAÑA DE GESTIÓN DE ROSTER ---
with tab_roster:
    st.subheader("⚙️ Carga Masiva y Control del Roster de Artistas")
    st.write("Usa este módulo para inyectar tus listas de nombres artísticos en bloque de forma masiva.")
    
    # Opción 1: Subir Archivo (.txt o .csv)
    uploaded_file = st.file_uploader("Subir archivo de artistas (Formato de texto .txt con un nombre por línea)", type=["txt", "csv"])
    
    if uploaded_file is not None:
        # Leer el contenido del archivo subido
        bytes_data = uploaded_file.read()
        string_data = bytes_data.decode("utf-8")
        nombres_archivo = [line.strip() for line in string_data.split("\n") if line.strip()]
        
        st.info(f"📋 Se detectaron **{len(nombres_archivo)}** artistas listos para cargar.")
        
        if st.button("Confirmar e Inyectar Lista de Archivo"):
            conn = sqlite3.connect("jatune_production.db")
            cursor = conn.cursor()
            nuevos, duplicados = 0, 0
            for nombre in nombres_archivo:
                try:
                    cursor.execute("INSERT INTO artistas (nombre, fecha_creacion) VALUES (?, ?)", (nombre, time.strftime("%Y-%m-%d")))
                    nuevos += 1
                except sqlite3.IntegrityError:
                    duplicados += 1
            conn.commit()
            conn.close()
            st.success(f"🚀 ¡Inyección Masiva Exitosa! Se agregaron **{nuevos}** artistas nuevos al Roster ({duplicados} ya existían).")
            st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Artistas Registrados Actualmente en Sistema")
    conn = sqlite3.connect("jatune_production.db")
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, fecha_creacion FROM artistas ORDER BY id DESC")
    todos_artistas = cursor.fetchall()
    conn.close()
    
    if todos_artistas:
        for idx, (name, fecha) in enumerate(todos_artistas):
            st.text(f"{idx+1}. {name} (Registrado el: {fecha})")
    else:
        st.info("No hay artistas registrados en el Roster de la Base de Datos todavía.")
