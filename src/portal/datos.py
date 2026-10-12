"""De la base a lo que el portal enseña. Solo lee.

El descuento que sale de aquí es entre DOS LECTURAS NUESTRAS, fechadas las dos.
Nunca el precio tachado de la tienda: ese «antes» es de ellos y miente la mitad
de las veces. Es la misma invariante que rige las alertas desde la Etapa 1, y el
portal no la relaja.
"""

import sqlite3
from datetime import datetime, timezone

# `LAG` da la lectura previa del mismo producto sin traerse el histórico entero.
# El desempate por `id` hace falta porque `capturado_el` tiene resolución de
# segundo y dos lecturas pueden empatar.
_CONSULTA = """
WITH ordenadas AS (
    SELECT h.producto_id,
           h.precio_internet,
           h.capturado_el,
           h.disponible,
           LAG(h.precio_internet) OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el, h.id
           ) AS precio_anterior,
           LAG(h.capturado_el) OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el, h.id
           ) AS fecha_anterior,
           ROW_NUMBER() OVER (
               PARTITION BY h.producto_id ORDER BY h.capturado_el DESC, h.id DESC
           ) AS fila
      FROM historico_precios h
)
SELECT p.producto_solotodo AS articulo,
       p.tienda,
       p.titulo,
       p.url,
       p.imagen_url,
       o.disponible,
       o.precio_internet,
       o.capturado_el,
       o.precio_anterior,
       o.fecha_anterior,
       (SELECT MIN(h2.precio_internet)
          FROM historico_precios h2
         WHERE h2.producto_id = p.id
           AND h2.capturado_el >= datetime('now', :ventana)) AS minimo
  FROM ordenadas o
  JOIN productos p ON p.id = o.producto_id
 WHERE o.fila = 1
 ORDER BY p.tienda, p.titulo
"""


def _descuento(precio: int, anterior: int | None) -> int:
    """Cuánto bajó, en porcentaje entero. Cero si no bajó o no hay con qué."""
    if not anterior or anterior <= 0 or precio >= anterior:
        # Un precio que subió no es una oferta, y sin lectura previa no hay
        # nada que comparar. En los dos casos el portal no enseña insignia.
        return 0
    return round((anterior - precio) / anterior * 100)


def datos_del_portal(con: sqlite3.Connection, ventana_dias: int = 90) -> dict:
    """La foto que consume la página. No escribe nada."""
    filas = con.execute(
        _CONSULTA, {"ventana": f"-{int(ventana_dias)} days"}
    ).fetchall()

    ofertas = []
    for f in filas:
        ofertas.append(
            {
                "articulo": f["articulo"],
                "tienda": f["tienda"],
                "titulo": f["titulo"],
                "url": f["url"],
                "imagen": f["imagen_url"],
                "disponible": bool(f["disponible"]),
                "precio": f["precio_internet"],
                "fecha": f["capturado_el"],
                "precio_anterior": f["precio_anterior"],
                "fecha_anterior": f["fecha_anterior"],
                "descuento_pct": _descuento(f["precio_internet"], f["precio_anterior"]),
                "minimo_historico": f["minimo"],
            }
        )

    return {
        "generado_el": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "productos": len(ofertas),
        "tiendas": len({o["tienda"] for o in ofertas}),
        "ofertas": ofertas,
    }
