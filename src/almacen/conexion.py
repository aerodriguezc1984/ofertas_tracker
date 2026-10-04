"""Apertura de la base de datos SQLite."""

import sqlite3
from pathlib import Path

ESQUEMA = Path(__file__).parent / "esquema.sql"


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
    return con
