import os
import random
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# =========================================================
# JATune Production - Frontend Streamlit
# Arquitectura: Artista -> Álbum/EP/Sencillo -> Canción
# =========================================================

DB_PATH = "jatune_production.db"
DEFAULT_RENDER_API_URL = "https://api-suno-nptk.onrender.com"

TIPOS_VALIDOS = {
    "SENCILLO": "Sencillo",
    "SINGLE": "Sencillo",
    "EP": "EP",
    "ALBUM": "Álbum",
    "ÁLBUM": "Álbum",
}

ESTADOS_VALIDOS = {
    "Pendiente",
    "Generando",
    "Completada",
    "Error",
    "Reintentar",
    "Descartada",
    "Publicada",
    "Distribuida",
}

ESTADOS_LEGACY = {
    "LISTO": "Completada",
    "COMPLETADO": "Completada",
    "COMPLETADA": "Completada",
    "PENDIENTE": "Pendiente",
    "GENERANDO": "Generando",
    "ERROR": "Error",
}


def get_secret_or_env(key: str, default: str = "") -> str:
    """Lee configuración desde Streamlit secrets o variables de entorno."""
    try:
        value = st.secrets.get(key, None)  # type: ignore[attr-defined]
        if value is not None:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, default)


RENDER_API_URL = get_secret_or_env("BACKEND_URL", DEFAULT_RENDER_API_URL).rstrip("/")
JATUNE_API_KEY = get_secret_or_env("JATUNE_API_KEY", "")


# =========================================================
# Base de datos
# =========================================================


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@st.cache_resource
def get_cached_db_path() -> str:
    return DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_cached_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_columns(conn: sqlite3.Connection, table_name: str) -> List[str]:
    if not table_exists(conn, table_name):
        return []
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def normalizar_tipo(tipo_raw: str) -> str:
    tipo = (tipo_raw or "").strip().upper()
    if tipo not in TIPOS_VALIDOS:
        raise ValueError("Tipo inválido. Usa solo: Sencillo, EP o Álbum.")
    return TIPOS_VALIDOS[tipo]


def normalizar_estado(estado_raw: Optional[str]) -> str:
    if not estado_raw:
        return "Pendiente"
    estado_upper = estado_raw.strip().upper()
    if estado_upper in ESTADOS_LEGACY:
        return ESTADOS_LEGACY[estado_upper]
    estado_title = estado_raw.strip().capitalize()
    return estado_title if estado_title in ESTADOS_VALIDOS else "Pendiente"


def create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artistas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            fecha_creacion TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS albumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artista_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('Sencillo', 'EP', 'Álbum')),
            fecha_creacion TEXT NOT NULL,
            FOREIGN KEY (artista_id) REFERENCES artistas(id) ON DELETE CASCADE,
            UNIQUE(artista_id, titulo, tipo)
        );

        CREATE TABLE IF NOT EXISTS canciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            genero_prompt TEXT NOT NULL,
            audio_url TEXT,
            image_url TEXT,
            video_url TEXT,
            clip_id TEXT,
            estado TEXT NOT NULL DEFAULT 'Pendiente'
                CHECK(estado IN ('Pendiente', 'Generando', 'Completada', 'Error', 'Reintentar', 'Descartada', 'Publicada', 'Distribuida')),
            error_detalle TEXT,
            fecha_creacion TEXT NOT NULL,
            fecha_actualizacion TEXT,
            FOREIGN KEY (album_id) REFERENCES albumes(id) ON DELETE CASCADE,
            UNIQUE(album_id, titulo)
        );

        CREATE INDEX IF NOT EXISTS idx_albumes_artista_id ON albumes(artista_id);
        CREATE INDEX IF NOT EXISTS idx_canciones_album_id ON canciones(album_id);
        CREATE INDEX IF NOT EXISTS idx_canciones_estado ON canciones(estado);
        CREATE INDEX IF NOT EXISTS idx_canciones_clip_id ON canciones(clip_id);
        """
    )


def migrate_legacy_schema() -> None:
    """Migra la tabla plana canciones antigua hacia la jerarquía nueva."""
    with get_conn() as conn:
        canciones_cols = get_columns(conn, "canciones")
        legacy_table = None

        if canciones_cols and "album_id" not in canciones_cols:
            legacy_table = f"canciones_legacy_{int(time.time())}"
            conn.execute(f"ALTER TABLE canciones RENAME TO {legacy_table}")

        create_core_schema(conn)

        if legacy_table:
            legacy_rows = conn.execute(f"SELECT * FROM {legacy_table}").fetchall()
            for row in legacy_rows:
                artista_id = row["artista_id"] if "artista_id" in row.keys() else None
                artista_nombre = "Artista Legacy"

                if artista_id:
                    artista_row = conn.execute(
                        "SELECT nombre FROM artistas WHERE id=?",
                        (artista_id,),
                    ).fetchone()
                    if artista_row:
                        artista_nombre = artista_row["nombre"]

                nuevo_artista_id = get_or_create_artista(conn, artista_nombre)
                album_id = get_or_create_album(conn, nuevo_artista_id, "Masters Importados", "Sencillo")

                titulo = row["titulo"] if "titulo" in row.keys() and row["titulo"] else "Track Importado"
                genero = row["genero"] if "genero" in row.keys() and row["genero"] else "Prompt no especificado"
                audio_url = row["audio_url"] if "audio_url" in row.keys() else None
                estado = normalizar_estado(row["estado"] if "estado" in row.keys() else None)

                cancion_id, _ = create_or_update_cancion(conn, album_id, titulo, genero)
                conn.execute(
                    """
                    UPDATE canciones
                    SET audio_url=?, estado=?, fecha_actualizacion=?
                    WHERE id=?
                    """,
                    (audio_url, estado, now_iso(), cancion_id),
                )


def init_db() -> None:
    migrate_legacy_schema()


# =========================================================
# CRUD catálogo
# =========================================================


def get_or_create_artista(conn: sqlite3.Connection, nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del artista no puede estar vacío.")

    conn.execute(
        "INSERT OR IGNORE INTO artistas (nombre, fecha_creacion) VALUES (?, ?)",
        (nombre, now_iso()),
    )
    row = conn.execute("SELECT id FROM artistas WHERE nombre=?", (nombre,)).fetchone()
    return int(row["id"])


def get_or_create_album(conn: sqlite3.Connection, artista_id: int, titulo: str, tipo: str) -> int:
    titulo = titulo.strip()
    tipo = normalizar_tipo(tipo)
    if not titulo:
        raise ValueError("El título del álbum/EP/Sencillo no puede estar vacío.")

    conn.execute(
        """
        INSERT OR IGNORE INTO albumes (artista_id, titulo, tipo, fecha_creacion)
        VALUES (?, ?, ?, ?)
        """,
        (artista_id, titulo, tipo, now_iso()),
    )
    row = conn.execute(
        """
        SELECT id FROM albumes
        WHERE artista_id=? AND titulo=? AND tipo=?
        """,
        (artista_id, titulo, tipo),
    ).fetchone()
    return int(row["id"])


def create_or_update_cancion(
    conn: sqlite3.Connection,
    album_id: int,
    titulo: str,
    genero_prompt: str,
) -> Tuple[int, str]:
    titulo = titulo.strip()
    genero_prompt = genero_prompt.strip()

    if not titulo:
        raise ValueError("El título de la canción no puede estar vacío.")
    if not genero_prompt:
        raise ValueError("El género o prompt musical no puede estar vacío.")

    existing = conn.execute(
        "SELECT id FROM canciones WHERE album_id=? AND titulo=?",
        (album_id, titulo),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE canciones
            SET genero_prompt=?, fecha_actualizacion=?
            WHERE id=?
            """,
            (genero_prompt, now_iso(), existing["id"]),
        )
        return int(existing["id"]), "actualizada"

    conn.execute(
        """
        INSERT INTO canciones (album_id, titulo, genero_prompt, estado, fecha_creacion)
        VALUES (?, ?, ?, 'Pendiente', ?)
        """,
        (album_id, titulo, genero_prompt, now_iso()),
    )
    row = conn.execute("SELECT last_insert_rowid() AS id").fetchone()
    return int(row["id"]), "creada"


def actualizar_cancion_resultado(
    cancion_id: int,
    estado: str,
    audio_url: Optional[str] = None,
    clip_id: Optional[str] = None,
    image_url: Optional[str] = None,
    video_url: Optional[str] = None,
    error_detalle: Optional[str] = None,
) -> None:
    estado = normalizar_estado(estado)
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE canciones
            SET estado=?,
                audio_url=COALESCE(?, audio_url),
                clip_id=COALESCE(?, clip_id),
                image_url=COALESCE(?, image_url),
                video_url=COALESCE(?, video_url),
                error_detalle=?,
                fecha_actualizacion=?
            WHERE id=?
            """,
            (estado, audio_url, clip_id, image_url, video_url, error_detalle, now_iso(), cancion_id),
        )


def obtener_artistas() -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute("SELECT id, nombre, fecha_creacion FROM artistas ORDER BY nombre").fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def obtener_catalogo() -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                ar.id AS artista_id,
                ar.nombre AS artista,
                al.id AS album_id,
                al.titulo AS album,
                al.tipo AS tipo,
                ca.id AS cancion_id,
                ca.titulo AS cancion,
                ca.genero_prompt,
                ca.estado,
                ca.audio_url,
                ca.clip_id,
                ca.fecha_creacion,
                ca.fecha_actualizacion,
                ca.error_detalle
            FROM canciones ca
            JOIN albumes al ON ca.album_id = al.id
            JOIN artistas ar ON al.artista_id = ar.id
            ORDER BY ar.nombre, al.titulo, ca.id
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def obtener_albumes_por_artista(artista_id: int) -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, titulo, tipo, fecha_creacion
            FROM albumes
            WHERE artista_id=?
            ORDER BY fecha_creacion DESC, titulo
            """,
            (artista_id,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def obtener_canciones_por_estado(estados: Tuple[str, ...], limit: int = 10) -> List[Dict[str, Any]]:
    placeholders = ",".join(["?"] * len(estados))
    params: Tuple[Any, ...] = (*estados, limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                ca.id AS cancion_id,
                ca.titulo AS cancion,
                ca.genero_prompt,
                ca.estado,
                ca.clip_id,
                al.titulo AS album,
                al.tipo,
                ar.nombre AS artista
            FROM canciones ca
            JOIN albumes al ON ca.album_id = al.id
            JOIN artistas ar ON al.artista_id = ar.id
            WHERE ca.estado IN ({placeholders})
            ORDER BY ca.id
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# =========================================================
# Carga masiva estructurada
# =========================================================


def leer_archivo_masivo(uploaded_file) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    raw = uploaded_file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    registros: List[Dict[str, str]] = []
    errores: List[Dict[str, Any]] = []

    for idx, linea_original in enumerate(text.splitlines(), start=1):
        linea = linea_original.strip()
        if not linea or linea.startswith("#"):
            continue

        if idx == 1 and "artista" in linea.lower() and "canc" in linea.lower():
            continue

        partes = [p.strip() for p in linea.split("|")]
        if len(partes) != 5:
            errores.append({
                "linea": idx,
                "error": "La línea no tiene exactamente 5 columnas separadas por |",
                "contenido": linea_original,
            })
            continue

        artista, album, tipo, cancion, genero_prompt = partes
        if not all([artista, album, tipo, cancion, genero_prompt]):
            errores.append({
                "linea": idx,
                "error": "Hay campos vacíos",
                "contenido": linea_original,
            })
            continue

        try:
            tipo_normalizado = normalizar_tipo(tipo)
        except ValueError as exc:
            errores.append({"linea": idx, "error": str(exc), "contenido": linea_original})
            continue

        registros.append({
            "artista": artista,
            "album": album,
            "tipo": tipo_normalizado,
            "cancion": cancion,
            "genero_prompt": genero_prompt,
        })

    return registros, errores


def importar_catalogo_masivo(registros: List[Dict[str, str]]) -> Dict[str, int]:
    resumen = {
        "artistas_procesados": 0,
        "albumes_procesados": 0,
        "canciones_creadas": 0,
        "canciones_actualizadas": 0,
    }
    artistas_vistos = set()
    albumes_vistos = set()

    with get_conn() as conn:
        for item in registros:
            artista_id = get_or_create_artista(conn, item["artista"])
            album_id = get_or_create_album(conn, artista_id, item["album"], item["tipo"])
            _, accion = create_or_update_cancion(conn, album_id, item["cancion"], item["genero_prompt"])

            artistas_vistos.add(item["artista"])
            albumes_vistos.add((item["artista"], item["album"], item["tipo"]))
            if accion == "creada":
                resumen["canciones_creadas"] += 1
            else:
                resumen["canciones_actualizadas"] += 1

        resumen["artistas_procesados"] = len(artistas_vistos)
        resumen["albumes_procesados"] = len(albumes_vistos)

    return resumen


# =========================================================
# Backend Render
# =========================================================


def backend_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if JATUNE_API_KEY:
        headers["x-api-key"] = JATUNE_API_KEY
    return headers


def construir_prompt(item: Dict[str, Any]) -> str:
    return (
        f"Crea una canción profesional para el artista {item['artista']}. "
        f"Título: {item['cancion']}. Proyecto: {item['album']} ({item['tipo']}). "
        f"Estilo e instrucciones musicales: {item['genero_prompt']}. "
        "Producción moderna, mezcla limpia, estructura comercial y alto potencial para plataformas digitales."
    )


def extraer_primer_track(data: Any) -> Dict[str, Optional[str]]:
    candidate: Dict[str, Any] = {}

    if isinstance(data, list) and data:
        candidate = next((x for x in data if isinstance(x, dict) and x.get("audio_url")), data[0])
    elif isinstance(data, dict):
        if isinstance(data.get("tracks"), list) and data["tracks"]:
            candidate = data["tracks"][0]
        elif isinstance(data.get("clips"), list) and data["clips"]:
            candidate = data["clips"][0]
        else:
            candidate = data

    audio_url = candidate.get("audio_url") or candidate.get("audioUrl")
    if not audio_url and isinstance(data, dict) and isinstance(data.get("urls"), list) and data["urls"]:
        audio_url = data["urls"][0]

    return {
        "clip_id": candidate.get("id") or candidate.get("clip_id"),
        "audio_url": audio_url,
        "image_url": candidate.get("image_url") or candidate.get("imageUrl"),
        "video_url": candidate.get("video_url") or candidate.get("videoUrl"),
        "status": candidate.get("status"),
    }


def generar_cancion_backend(item: Dict[str, Any], wait_audio: bool = True, make_instrumental: bool = False) -> Dict[str, Optional[str]]:
    payload = {
        "prompt": construir_prompt(item),
        "make_instrumental": make_instrumental,
        "wait_audio": wait_audio,
    }
    response = requests.post(
        f"{RENDER_API_URL}/api/generate",
        json=payload,
        headers=backend_headers(),
        timeout=600,
    )
    response.raise_for_status()
    return extraer_primer_track(response.json())


def consultar_clips_backend(clip_ids: List[str]) -> List[Dict[str, Any]]:
    if not clip_ids:
        return []
    response = requests.get(
        f"{RENDER_API_URL}/api/get?ids={','.join(clip_ids)}",
        headers=backend_headers(),
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


# =========================================================
# UI helpers
# =========================================================


def generar_nombre_artistico() -> str:
    prefijos = ["Aether", "Zuki", "Lumo", "Vibe", "Nova", "Drako", "Neon", "Sintax", "Baty", "Yleg", "JMAR", "JJ"]
    nucleos = ["Pop", "Focus", "Chispero", "Tune", "Moon", "Studio", "Legacy", "Sonic", "Beat", "Wave"]
    sufijos = ["CXT", "Project", "Bass", "Mundo", "Loop", "Gold", "Session"]
    while True:
        nombre = f"{random.choice(prefijos)} {random.choice(nucleos)}"
        if random.random() <= 0.5:
            nombre = f"{nombre} {random.choice(sufijos)}"
        with get_conn() as conn:
            existe = conn.execute("SELECT id FROM artistas WHERE nombre=?", (nombre,)).fetchone()
        if not existe:
            return nombre


def render_metric_card(label: str, value: str, help_text: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-help">{help_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def aplicar_estilos() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: radial-gradient(circle at top left, #16213e 0, #07111f 36%, #020617 100%); color: #e5e7eb; }
        [data-testid="stSidebar"] { background: #050816; }
        h1, h2, h3 { letter-spacing: -0.04em; }
        .metric-card { border: 1px solid rgba(255,255,255,.12); background: rgba(15,23,42,.72); border-radius: 22px; padding: 20px; min-height: 135px; box-shadow: 0 18px 40px rgba(0,0,0,.20); }
        .metric-label { color: #93c5fd; font-size: .8rem; font-weight: 700; }
        .metric-value { color: #facc15; font-size: 2rem; font-weight: 900; margin-top: 8px; }
        .metric-help { color: #94a3b8; font-size: .75rem; margin-top: 8px; text-transform: uppercase; letter-spacing: .18em; }
        .stButton>button { background: linear-gradient(135deg, #facc15, #fb7185); color: #020617; border: 0; border-radius: 12px; font-weight: 900; min-height: 44px; }
        .stButton>button:hover { color: #020617; filter: brightness(1.08); }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# Vistas
# =========================================================


def vista_dashboard() -> None:
    df = obtener_catalogo()
    artistas_df = obtener_artistas()

    total_artistas = len(artistas_df)
    total_albumes = int(df[["artista", "album", "tipo"]].drop_duplicates().shape[0]) if not df.empty else 0
    total_canciones = len(df)
    completadas = int((df["estado"] == "Completada").sum()) if not df.empty else 0
    pendientes = int((df["estado"] == "Pendiente").sum()) if not df.empty else 0
    errores = int((df["estado"] == "Error").sum()) if not df.empty else 0

    st.markdown("# 🎛️ JATune Production")
    st.caption("Centro de control para catálogo, carga masiva y generación musical desde Render.")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Artistas", str(total_artistas), "Roster activo")
    with c2:
        render_metric_card("Álbumes / EPs", str(total_albumes), "Proyectos")
    with c3:
        render_metric_card("Canciones", str(total_canciones), "Tracks registrados")
    with c4:
        render_metric_card("Completadas", str(completadas), "Masters listos")

    st.markdown("---")
    c5, c6, c7 = st.columns(3)
    c5.metric("Pendientes", pendientes)
    c6.metric("Errores", errores)
    c7.metric("Backend Render", RENDER_API_URL)

    if not df.empty:
        st.markdown("### Estado del pipeline")
        estado_df = df.groupby("estado").size().reset_index(name="cantidad")
        st.bar_chart(estado_df.set_index("estado"))


def vista_estudio_manual() -> None:
    st.subheader("🚀 Generador rápido con catálogo")
    artistas_df = obtener_artistas()

    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        modo_artista = st.radio("Artista", ["Seleccionar existente", "Crear manual", "Generar random"])
        artista_nombre = ""
        artista_id: Optional[int] = None

        if modo_artista == "Seleccionar existente" and not artistas_df.empty:
            artista_nombre = st.selectbox("Roster", artistas_df["nombre"].tolist())
        elif modo_artista == "Seleccionar existente":
            st.warning("No hay artistas registrados. Crea uno manual o carga roster.")
        elif modo_artista == "Crear manual":
            artista_nombre = st.text_input("Nombre del artista").strip()
        else:
            if "nombre_random_actual" not in st.session_state:
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
            if st.button("🎲 Cambiar nombre"):
                st.session_state["nombre_random_actual"] = generar_nombre_artistico()
            artista_nombre = st.session_state["nombre_random_actual"]
            st.info(f"Artista sugerido: **{artista_nombre}**")

        album_titulo = st.text_input("Título del álbum / EP / sencillo", value="Proyecto Inicial").strip()
        album_tipo = st.selectbox("Tipo", ["Sencillo", "EP", "Álbum"])

    with col2:
        cancion_titulo = st.text_input("Título de la canción", value="Track 01").strip()
        genero_prompt = st.text_area("Género o prompt musical", height=140, placeholder="Dembow Dominicano, bajo pesado, 120 BPM...")
        make_instrumental = st.checkbox("Instrumental", value=False)
        wait_audio = st.checkbox("Esperar audio final", value=True)

    if st.button("Guardar y generar ahora ⚡", type="primary"):
        if not artista_nombre or not album_titulo or not cancion_titulo or not genero_prompt:
            st.error("Completa artista, proyecto, canción y prompt.")
            return

        with get_conn() as conn:
            artista_id = get_or_create_artista(conn, artista_nombre)
            album_id = get_or_create_album(conn, artista_id, album_titulo, album_tipo)
            cancion_id, _ = create_or_update_cancion(conn, album_id, cancion_titulo, genero_prompt)

        item = {
            "cancion_id": cancion_id,
            "artista": artista_nombre,
            "album": album_titulo,
            "tipo": album_tipo,
            "cancion": cancion_titulo,
            "genero_prompt": genero_prompt,
        }

        try:
            actualizar_cancion_resultado(cancion_id, "Generando")
            with st.spinner("Generando en Render Pro..."):
                result = generar_cancion_backend(item, wait_audio=wait_audio, make_instrumental=make_instrumental)
            estado_final = "Completada" if result.get("audio_url") else "Generando"
            actualizar_cancion_resultado(
                cancion_id,
                estado_final,
                audio_url=result.get("audio_url"),
                clip_id=result.get("clip_id"),
                image_url=result.get("image_url"),
                video_url=result.get("video_url"),
            )
            st.success(f"Canción enviada correctamente. Estado: {estado_final}")
            if result.get("audio_url"):
                st.audio(result["audio_url"])
        except Exception as exc:
            actualizar_cancion_resultado(cancion_id, "Error", error_detalle=str(exc))
            st.error(f"Error generando canción: {exc}")


def vista_catalogo() -> None:
    st.subheader("📁 Catálogo musical jerárquico")
    df = obtener_catalogo()

    if df.empty:
        st.info("Todavía no hay canciones cargadas. Usa Administración → Carga estructurada.")
        return

    col1, col2, col3 = st.columns(3)
    artista_sel = col1.selectbox("Artista", ["Todos"] + sorted(df["artista"].dropna().unique().tolist()))
    estado_sel = col2.selectbox("Estado", ["Todos"] + sorted(df["estado"].dropna().unique().tolist()))
    tipo_sel = col3.selectbox("Tipo", ["Todos"] + sorted(df["tipo"].dropna().unique().tolist()))

    df_view = df.copy()
    if artista_sel != "Todos":
        df_view = df_view[df_view["artista"] == artista_sel]
    if estado_sel != "Todos":
        df_view = df_view[df_view["estado"] == estado_sel]
    if tipo_sel != "Todos":
        df_view = df_view[df_view["tipo"] == tipo_sel]

    st.dataframe(df_view, use_container_width=True, hide_index=True)

    st.markdown("### Reproductor rápido")
    audios = df_view[df_view["audio_url"].notna() & (df_view["audio_url"] != "")]
    if audios.empty:
        st.caption("No hay audios disponibles en el filtro actual.")
    else:
        for _, row in audios.head(10).iterrows():
            st.write(f"🎵 **{row['cancion']}** — {row['artista']} / {row['album']}")
            st.audio(row["audio_url"])


def vista_generacion_masiva() -> None:
    st.subheader("🏭 Generación masiva desde canciones pendientes")

    col1, col2, col3 = st.columns(3)
    limite = int(col1.number_input("Cantidad máxima", min_value=1, max_value=25, value=5, step=1))
    wait_audio = col2.checkbox("Esperar audio final", value=True)
    make_instrumental = col3.checkbox("Instrumental", value=False)

    pendientes = obtener_canciones_por_estado(("Pendiente", "Reintentar"), limit=limite)
    st.metric("Pendientes encontradas", len(pendientes))

    if pendientes:
        st.dataframe(pd.DataFrame(pendientes), use_container_width=True, hide_index=True)

    if pendientes and st.button("Generar pendientes ahora", type="primary"):
        progress = st.progress(0)
        log_area = st.empty()
        resultados = []

        for i, item in enumerate(pendientes, start=1):
            try:
                actualizar_cancion_resultado(item["cancion_id"], "Generando")
                log_area.info(f"Generando {i}/{len(pendientes)}: {item['artista']} - {item['cancion']}")
                result = generar_cancion_backend(item, wait_audio=wait_audio, make_instrumental=make_instrumental)
                estado_final = "Completada" if result.get("audio_url") else "Generando"
                actualizar_cancion_resultado(
                    item["cancion_id"],
                    estado_final,
                    audio_url=result.get("audio_url"),
                    clip_id=result.get("clip_id"),
                    image_url=result.get("image_url"),
                    video_url=result.get("video_url"),
                )
                resultados.append({"cancion": item["cancion"], "artista": item["artista"], "estado": estado_final, "audio_url": result.get("audio_url")})
            except Exception as exc:
                actualizar_cancion_resultado(item["cancion_id"], "Error", error_detalle=str(exc))
                resultados.append({"cancion": item["cancion"], "artista": item["artista"], "estado": "Error", "detalle": str(exc)})

            progress.progress(i / len(pendientes))

        st.success("Proceso de generación finalizado.")
        st.dataframe(pd.DataFrame(resultados), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Actualizar canciones en estado Generando")
    generando = obtener_canciones_por_estado(("Generando",), limit=25)
    st.caption(f"Canciones en seguimiento: {len(generando)}")

    if generando and st.button("Consultar estado en backend"):
        clip_map = {item["clip_id"]: item for item in generando if item.get("clip_id")}
        try:
            clips = consultar_clips_backend(list(clip_map.keys()))
            actualizadas = 0
            for clip in clips:
                clip_id = clip.get("id")
                item = clip_map.get(clip_id)
                if not item:
                    continue
                audio_url = clip.get("audio_url")
                estado = clip.get("status")
                if audio_url:
                    actualizar_cancion_resultado(
                        item["cancion_id"],
                        "Completada",
                        audio_url=audio_url,
                        image_url=clip.get("image_url"),
                        video_url=clip.get("video_url"),
                    )
                    actualizadas += 1
                elif estado == "error":
                    actualizar_cancion_resultado(item["cancion_id"], "Error", error_detalle=clip.get("error_message"))
            st.success(f"Actualizadas: {actualizadas}")
        except Exception as exc:
            st.error(f"No fue posible consultar el backend: {exc}")


def vista_admin() -> None:
    st.subheader("⚙️ Administración")

    with st.expander("📥 Carga masiva estructurada de catálogo", expanded=True):
        st.caption("Formato: Artista | Álbum/EP/Sencillo | Tipo | Canción | Género o Prompt Musical")
        ejemplo = "\n".join([
            "Zyphorix | Galactic Vibe | EP | Nebula Dance | Dembow Dominicano, Bajo Pesado, 120 BPM",
            "Zyphorix | Galactic Vibe | EP | Solar Flare | Spatial Trap, Sintetizadores Futuristas",
            "Velnora | Sentimiento Puro | Sencillo | Sabor Calle | Bachata Urbana, Guitarra Afilada",
            "Jeantune | Amor Digital | Álbum | Besos en la Nube | Pop Urbano Romántico, Synth Latino, 95 BPM",
        ])
        st.download_button("Descargar plantilla ejemplo", ejemplo, file_name="plantilla_catalogo_jatune.txt", mime="text/plain")

        uploaded_file = st.file_uploader("Sube archivo .txt o .csv separado por tuberías |", type=["txt", "csv"], key="catalog_upload")
        if uploaded_file is not None:
            registros, errores = leer_archivo_masivo(uploaded_file)
            c1, c2, c3 = st.columns(3)
            c1.metric("Registros válidos", len(registros))
            c2.metric("Errores", len(errores))
            c3.metric("Listo", "Sí" if registros and not errores else "No")

            if registros:
                st.markdown("#### Vista previa")
                st.dataframe(pd.DataFrame(registros), use_container_width=True, hide_index=True)
            if errores:
                st.markdown("#### Errores detectados")
                st.dataframe(pd.DataFrame(errores), use_container_width=True, hide_index=True)
                st.warning("Corrige los errores antes de importar para mantener el catálogo limpio.")

            if registros and not errores:
                if st.button("Importar catálogo musical", type="primary"):
                    resumen = importar_catalogo_masivo(registros)
                    st.success("Catálogo importado correctamente.")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Artistas", resumen["artistas_procesados"])
                    c2.metric("Álbumes / EPs", resumen["albumes_procesados"])
                    c3.metric("Canciones nuevas", resumen["canciones_creadas"])
                    c4.metric("Actualizadas", resumen["canciones_actualizadas"])
                    st.rerun()

    with st.expander("👥 Carga rápida de roster de artistas"):
        roster_file = st.file_uploader("Archivo con un artista por línea", type=["txt", "csv"], key="roster_upload")
        if roster_file is not None:
            raw = roster_file.read()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            nombres = [line.strip() for line in text.splitlines() if line.strip()]
            st.info(f"Se detectaron {len(nombres)} nombres.")
            if st.button("Inyectar roster"):
                nuevos, duplicados = 0, 0
                with get_conn() as conn:
                    for nombre in nombres:
                        before = conn.execute("SELECT id FROM artistas WHERE nombre=?", (nombre,)).fetchone()
                        get_or_create_artista(conn, nombre)
                        if before:
                            duplicados += 1
                        else:
                            nuevos += 1
                st.success(f"Roster actualizado. Nuevos: {nuevos} | Duplicados: {duplicados}")
                st.rerun()

    with st.expander("🔧 Configuración actual"):
        st.write("Backend:", RENDER_API_URL)
        st.write("API Key propia:", "Configurada" if JATUNE_API_KEY else "No configurada")
        st.caption("Si agregas JATUNE_API_KEY en Render backend, agrega la misma clave en Streamlit secrets.")


# =========================================================
# App
# =========================================================


st.set_page_config(
    page_title="JATune Production — Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)
aplicar_estilos()
init_db()

with st.sidebar:
    st.markdown("## 🎵 JATune")
    st.caption("Mini disquera automatizada")
    st.markdown("---")
    st.write("**Backend:**")
    st.code(RENDER_API_URL, language="text")
    st.markdown("---")
    st.caption("Flujo: idea → catálogo → generación → master → publicación.")


tab_dashboard, tab_estudio, tab_catalogo, tab_masivo, tab_admin = st.tabs([
    "📊 Dashboard",
    "🚀 Estudio",
    "📁 Catálogo",
    "🏭 Generación Masiva",
    "⚙️ Administración",
])

with tab_dashboard:
    vista_dashboard()

with tab_estudio:
    vista_estudio_manual()

with tab_catalogo:
    vista_catalogo()

with tab_masivo:
    vista_generacion_masiva()

with tab_admin:
    vista_admin()
