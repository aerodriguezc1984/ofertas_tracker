"""Apertura de la base de datos SQLite."""

import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).parent / "esquema.sql"

# Columnas añadidas después de la primera versión del esquema. `CREATE TABLE IF
# NOT EXISTS` no las lleva a una base que ya existe, así que hay que añadirlas a
# mano. Formato: (tabla, columna, declaración).
#
# Disciplina pura, sin red de seguridad: toda prueba crea la base desde cero,
# así que ninguna vigila que una columna nueva del esquema también se añada
# aquí. Y la declaración tiene un límite real: `ALTER TABLE ... ADD COLUMN` no
# admite `UNIQUE`, y solo admite `NOT NULL` si lleva `DEFAULT` —comprobado: sin
# `DEFAULT` se acepta sobre una tabla vacía y se rechaza sobre una con filas—,
# así que una declaración mal formada pasaría la suite entera y solo
# reventaría sobre la base real del usuario.
COLUMNAS_NUEVAS = [
    ("productos", "producto_solotodo", "INTEGER"),
]


def _migrar(con: sqlite3.Connection) -> None:
    """Añade a una base anterior las columnas que su esquema no tenía.

    Los nombres de tabla y columna no se pueden parametrizar en SQL, así que se
    interpolan — son literales de `COLUMNAS_NUEVAS`, escritos aquí, nunca datos
    de fuera.
    """
    for tabla, columna, declaracion in COLUMNAS_NUEVAS:
        presentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
        if columna not in presentes:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {declaracion}")


def abrir(ruta: Path | str) -> sqlite3.Connection:
    """Abre la base en modo WAL y deja el esquema aplicado.

    El modo WAL permite leer mientras se escribe, que es lo que necesita un
    proceso que captura y consulta a la vez. `isolation_level = None` deja el
    control de las transacciones en nuestras manos en vez de en las del
    envoltorio de Python.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(ruta, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    _migrar(con)
    return con
