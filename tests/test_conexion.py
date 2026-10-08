import sqlite3

from almacen.conexion import abrir

# El esquema tal y como era ANTES de esta etapa. Se copia aquí a propósito: una
# prueba de migración que lea el esquema actual no prueba nada, porque migraría
# de la versión nueva a la versión nueva.
ESQUEMA_ANTERIOR = """
CREATE TABLE productos (
    id              INTEGER PRIMARY KEY,
    tienda          TEXT    NOT NULL,
    sku_externo     TEXT    NOT NULL,
    ean             TEXT,
    titulo          TEXT    NOT NULL,
    url             TEXT    NOT NULL UNIQUE,
    imagen_url      TEXT,
    creado_el       TEXT    NOT NULL DEFAULT (datetime('now')),
    ultima_revision TEXT,
    UNIQUE (tienda, sku_externo)
);
"""


def test_abrir_crea_las_tablas_y_activa_wal(tmp_path):
    con = abrir(tmp_path / "prueba.db")

    tablas = {
        f["name"]
        for f in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"productos", "historico_precios", "registro_alertas"} <= tablas

    modo = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "wal"

    claves = con.execute("PRAGMA foreign_keys").fetchone()[0]
    assert claves == 1


def test_abrir_es_idempotente(tmp_path):
    ruta = tmp_path / "prueba.db"
    abrir(ruta)
    con = abrir(ruta)  # no debe estallar al reaplicar el esquema
    assert con.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0


def test_una_base_anterior_gana_la_columna_sin_perder_sus_datos(tmp_path):
    """El caso que ninguna otra prueba puede ver.

    Todas las demás crean su base desde cero, donde `CREATE TABLE` ya trae la
    columna. Sobre una base que ya existe no llega nunca, y el único afectado
    sería el usuario con su histórico dentro.
    """
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript(ESQUEMA_ANTERIOR)
    vieja.execute(
        "INSERT INTO productos (tienda, sku_externo, titulo, url)"
        " VALUES ('paris', 'S1', 'Notebook', 'https://www.paris.cl/n-S1.html')"
    )
    vieja.commit()
    vieja.close()

    con = abrir(ruta)

    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "producto_solotodo" in columnas

    fila = con.execute("SELECT tienda, sku_externo, titulo FROM productos").fetchone()
    assert (fila["tienda"], fila["sku_externo"], fila["titulo"]) == (
        "paris", "S1", "Notebook",
    )


def test_la_base_nueva_trae_la_columna_de_comparacion(tmp_path):
    """Una base creada hoy no necesita migración: la columna viene del esquema."""
    con = abrir(tmp_path / "nueva.db")
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "ultima_comparacion" in columnas


def test_una_base_sin_la_columna_de_comparacion_se_migra(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` no añade columnas a una tabla que ya existe."""
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript(
        """
        CREATE TABLE productos (
            id                INTEGER PRIMARY KEY,
            tienda            TEXT    NOT NULL,
            sku_externo       TEXT    NOT NULL,
            ean               TEXT,
            producto_solotodo INTEGER,
            titulo            TEXT    NOT NULL,
            url               TEXT    NOT NULL UNIQUE,
            imagen_url        TEXT,
            creado_el         TEXT    NOT NULL DEFAULT (datetime('now')),
            ultima_revision   TEXT,
            UNIQUE (tienda, sku_externo)
        );
        INSERT INTO productos (tienda, sku_externo, titulo, url)
             VALUES ('paris', '123', 'Un notebook', 'https://ejemplo/1');
        """
    )
    vieja.commit()
    vieja.close()

    con = abrir(ruta)
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(productos)")}
    assert "ultima_comparacion" in columnas
    # Y la fila que ya estaba sigue ahí, con la columna nueva a nulo.
    fila = con.execute("SELECT sku_externo, ultima_comparacion FROM productos").fetchone()
    assert fila["sku_externo"] == "123"
    assert fila["ultima_comparacion"] is None
