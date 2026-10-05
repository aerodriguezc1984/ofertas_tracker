"""Evita repetir la misma alerta hasta cansar al usuario.

Un rastreador que avisa de la misma oferta seis veces al día acaba silenciado,
y entonces no sirve para nada. Esta es la pieza que lo impide.
"""


def debe_notificar(anterior, precio: int, cooldown_dias: int) -> bool:
    """Se avisa si es la primera vez, si bajó más, o si pasó el descanso.

    `anterior` es la fila que devuelve `almacen.operaciones.ultima_alerta`, o
    None si nunca se avisó. Se recibe ya consultada para que esta capa no sepa
    de SQL.
    """
    if anterior is None:
        return True
    if precio < anterior["precio_notificado"]:
        return True
    return anterior["dias_desde"] > cooldown_dias
