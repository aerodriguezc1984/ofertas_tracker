"""Evita repetir la misma alerta hasta cansar al usuario.

Un rastreador que avisa de la misma oferta seis veces al día acaba silenciado,
y entonces no sirve para nada. Esta es la pieza que lo impide.
"""

import sqlite3

from almacen.operaciones import ultima_alerta


def debe_notificar(
    con: sqlite3.Connection,
    producto_id: int,
    regla: str,
    precio: int,
    cooldown_dias: int,
) -> bool:
    """Se avisa si es la primera vez, si bajó más, o si pasó el descanso."""
    anterior = ultima_alerta(con, producto_id, regla)
    if anterior is None:
        return True
    if precio < anterior["precio_notificado"]:
        return True
    return anterior["dias_desde"] > cooldown_dias
