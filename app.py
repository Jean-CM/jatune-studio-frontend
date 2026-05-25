import streamlit as st
import sqlite3
import requests
import random
import time

# URL de tu API de Suno en Render Pro (Asegúrate de que coincida con tu URL actual)
RENDER_API_URL = "https://api-suno-nptk.onrender.com"

# 1. INICIALIZACIÓN DE LA BASE DE DATOS LOCAL (SQLite)
# Guarda el historial y la relación de qué música pertenece a cada artista.
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

# 2. ALGORITMO DE NOMBRE ARTÍSTICO ALEATORIO (Random Inteligente)
# Combina raíces exclusivas para evitar nombres genéricos o repetidos en plataformas.
def generar_nombre_artistico():
    prefijos = ["Aether", "Zuki", "Lumo", "Vibe", "Nova", "Drako", "Neon", "Sintax", "Baty", "Yleg", "JMAR", "JJ"]
    nucleos = ["Pop", "Focus", "Chispero", "Tune", "Moon", "Studio", "Legacy", "Sonic", "Beat", "Wave"]
    sufijos = ["CXT", "Project", "Bass", "Mundo", "Loop", "Gold", "Session"]
    
    while True:
        # Genera una combinación única
        if random.random() > 0.5:
            nombre = f"{random.choice(prefijos)} {random.choice(nucleos)}"
        else:
            nombre = f"{random.choice(prefijos)} {random.choice(nucleos)} {random.choice(sufijos)}"
            
        # Validar en la base de datos que no se haya usado antes en JATune
        conn = sqlite3.connect("jatune_production.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM artistas WHERE nombre = ?", (nombre,))
        existe = cursor.fetchone()
        conn.close()
        
        if not existe:
            return nombre

# 3. INTERFAZ VISUAL (Configuración del Layout de Streamlit)
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
st.caption("Consola Centralizado de Automatización y Gestión de Catálogos")

# Pestañas principales de navegación
tab_estudio, tab_inventario = st.tabs(["🚀 Módulo de Producción", "📁 Catálogo e Historial"])

# --- TAB 1: MÓDULO DE PRODUCCIÓN ---
with tab_estudio:
    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.subheader("🤖 Control de Identidad (Artista)")
        opcion_artista = st.radio(
            "Selecciona el destino del catálogo:",
            ["Elegir Artista Existente", "Crear Nuevo Artista Personalizado", "Generar Artista Aleatorio (Random Exclusivo)"]
        )
        
        # Cargar artistas guardados en la DB
        conn = sqlite3.connect("jatune_production.db")
        cursor = conn.cursor()
        cursor.execute("SELECT nombre FROM artistas ORDER BY nombre ASC")
        artistas_guardados = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        artista_final = ""
        
        if opcion_artista == "Elegir Artista Existente":
            if artistas_guardados:
                artista_final = st.selectbox("Selecciona un artista de tu roster:", artistas_guardados)
            else:
                st.info("Aún no tienes artistas en la base de datos. Selecciona otra opción para fundar el primero.")
        
        elif opcion_artista == "Crear Nuevo Artista Personalizado":
            artista_final = st.text_input("Escribe el nombre del nuevo artista (ej: Jeantune, JCSTUDIO):").strip()
            
        elif opcion_artista == "Generar Artista Aleatorio (Random Exclusivo)":
            if "nombre_random_actual" not in st.session_state:
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
            
            if st.button("🎲 Cambiar Nombre Aleatorio"):
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
                
            artista_final = st.session_state["nombre_random_actual"]
            st.success(f"Artista asignado para este lote: **{artista_final}**")

    with col2:
        st.subheader("📝 Carga de Contenido Musical")
        modo_entrada = st.radio("Método de inyección:", ["Por Lote (Parámetros Fijos)", "Entrada Masiva (Pegar Bloque de Texto)"])
        
        lista_prompts = []
        
        if modo_entrada == "Por Lote (Parámetros Fijos)":
            cantidad = st.number_input("¿Cuántas canciones deseas generar para este lote?", min_value=1, max_value=20, value=1)
            genero_fijo = st.text_input("Ingresa el estilo/género (ej: Dembow Dominicano, Bajo Pesado, 120 BPM):")
            if genero_fijo:
                lista_prompts = [genero_fijo] * int(cantidad)
                
        elif modo_entrada == "Entrada Masiva (Pegar Bloque de Texto)":
            bloque_texto = st.text_area("Pega la lista estructurada de pistas (Una por línea):", height=180,
                                        placeholder="Track 1: Dembow Dominicano, Chapa Pesada\nTrack 2: Trap Melódico, 140 BPM\nTrack 3: Reggaeton Estilo Calle")
            if bloque_texto:
                lista_prompts = [line.strip() for line in bloque_texto.split("\n") if line.strip()]

    st.markdown("---")
    
    # BOTÓN MAESTRO DE PRODUCCIÓN
    if st.button("Lanzar Secuencia Automática a Render Pro ⚡"):
        if not artista_final or artista_final == "Presiona el botón para generar":
            st.error("Error: Debes definir una identidad de artista válida antes de enviar la cola de producción.")
        elif not lista_prompts:
            st.error("Error: No has ingresado ningún género o prompt para procesar.")
        else:
            progreso_status = st.empty()
            
            with st.spinner(f"Iniciando secuencia masiva... Conectando con el contenedor de Render para **{artista_final}**."):
                
                # 1. Asegurar el registro del artista en la DB local
                conn = sqlite3.connect("jatune_production.db")
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO artistas (nombre, fecha_creacion) VALUES (?, ?)", 
                               (artista_final, time.strftime("%Y-%m-%d")))
                cursor.execute("SELECT id FROM artistas WHERE nombre = ?", (artista_final,))
                artista_id = cursor.fetchone()[0]
                
                exitos = 0
                fallos = 0
                
                # 2. Ejecutar la cola de reproducción
                for idx, prompt_musical in enumerate(lista_prompts):
                    progreso_status.info(f"⏳ Procesando pista {idx+1}/{len(lista_prompts)}: *{prompt_musical}*...")
                    
                    try:
                        # Petición HTTP estructurada hacia tu API en Render Pro
                        payload = {"prompt": prompt_musical, "make_instrumental": True, "wait_audio": True}
                        response = requests.post(f"{RENDER_API_URL}/api/generate", json=payload, timeout=300)
                        
                        if response.status_code == 200:
                            data = response.json()
                            # Extraer las pistas devueltas por el backend de Suno
                            tracks = data.get("tracks", [{"title": f"Track {idx+1}", "audio_url": ""}])
                            
                            for track in tracks:
                                cursor.execute("""
                                    INSERT INTO canciones (artista_id, titulo, genero, audio_url, estado)
                                    VALUES (?, ?, ?, ?, ?)
                                """, (artista_id, track.get("title", f"Track {idx+1}"), prompt_musical, track.get("audio_url"), "Listo"))
                            exitos += 1
                        else:
                            fallos += 1
                            st.error(f"⚠️ El servidor respondió con error en la pista {idx+1} (Código {response.status_code}).")
                    except Exception as e:
                        fallos += 1
                        st.error(f"❌ Error de conexión con tu servicio en Render: {e}")
                
                conn.commit()
                conn.close()
                
                progreso_status.empty()
                st.success(f"¡Secuencia terminada! 🎯 Lote procesado para **{artista_final}**. Éxitos: {exitos} | Fallos: {fallos}")
                st.balloons()

# --- TAB 2: CATÁLOGO E HISTORIAL ---
with tab_inventario:
    st.subheader("📁 Inventario Global de JATune Production")
    
    conn = sqlite3.connect("jatune_production.db")
    cursor = conn.cursor()
    
    # Obtener el conteo consolidado de música generada por cada artista registrado
    cursor.execute("""
        SELECT a.nombre, COUNT(c.id), a.id 
        FROM artistas a LEFT JOIN canciones c ON a.id = c.artista_id 
        GROUP BY a.id ORDER BY COUNT(c.id) DESC
    """)
    res_artistas = cursor.fetchall()
    
    if res_artistas:
        col_inv1, col_inv2 = st.columns([1, 2])
        
        with col_inv1:
            st.markdown("### Resumen de Roster")
            for name, count, _ in res_artistas:
                st.metric(label=f"Artista: {name}", value=f"{count} tracks")
        
        with col_inv2:
            st.markdown("### Historial de Masters y Despliegue")
            artista_filtro = st.selectbox("Selecciona un perfil para auditar su música:", [row[0] for row in res_artistas])
            
            if artista_filtro:
                cursor.execute("""
                    SELECT c.titulo, c.genero, c.audio_url, c.estado 
                    FROM canciones c JOIN artistas a ON c.artista_id = a.id 
                    WHERE a.nombre = ? ORDER BY c.id DESC
                """, (artista_filtro,))
                tracks_artista = cursor.fetchall()
                
                if tracks_artista:
                    for titulo, genero, url, estado in tracks_artista:
                        with st.container():
                            st.write(f"🎵 **{titulo}** — *{genero}*")
                            if url:
                                st.audio(url)
                            st.caption(f"Estado de Distribución: **{estado}**")
                            st.markdown("---")
                else:
                    st.info("Este artista está registrado en el roster pero aún no se le ha generado música en este lote.")
    else:
        st.info("La base de datos local está limpia. Toda la música y los artistas que crees en el módulo anterior aparecerán aquí organizados automáticamente.")
        
    conn.close()
