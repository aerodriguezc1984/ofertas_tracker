"""Escrituras y consultas sobre la base. Nadie más toca SQL."""

import sqlite3

from fuentes.base import Captura


def alta_o_actualiza_producto(con: sqlite3.Connection, captura: Captura) -> int:
    """Devuelve el id del producto, dándolo de alta si es nuevo.

    La identidad del producto es el par (tienda, sku_externo). El título y la
    imagen se refrescan en cada pasada porque las tiendas los cambian.
    """
    con.execute(
        """
        INSERT INTO productos (tienda, sku_externo, titulo, url, imagen_url, ean,
                               ultima_revision)
             VALUES (:tienda, :sku, :titulo, :url, :imagen, :ean, datetime('now'))
        ON CONFLICT (tienda, sku_externo) DO UPDATE SET
                titulo          = excluded.titulo,
                imagen_url      = COALESCE(excluded.imagen_url, productos.imagen_url),
                ean             = COALESCE(excluded.ean, productos.ean),
                ultima_revision = datetime('now')
        """,
        {
            "tienda": captura.tienda,
            "sku": captura.sku_externo,
            "titulo": captura.titulo,
            "url": captura.url,
            "imagen": captura.imagen_url,
            "ean": captura.ean,
        },
    )
    fila = con.execute(
        "SELECT id FROM productos WHERE tienda = ? AND sku_externo = ?",
        (captura.tienda, captura.sku_externo),
    ).fetchone()
    return fila["id"]


def registrar_si_cambio(
    con: sqlite3.Connection, producto_id: int, captura: Captura
) -> bool:
    """Inserta en el histórico solo si algo cambió. Devuelve si insertó.

    El histórico es un registro de VARIACIONES, no de pasadas: insertar una fila
    por ejecución entierra los cambios reales bajo miles de filas idénticas.
    """
    ultima = con.execute(
        """
        SELECT precio_internet, precio_normal, precio_tarjeta, tarjeta_asociada, disponible
          FROM historico_precios
         WHERE producto_id = ?
         ORDER BY capturado_el DESC, id DESC
         LIMIT 1
        """,
        (producto_id,),
    ).fetchone()

    nuevo = (
        captura.precio_internet,
        captura.precio_normal,
        captura.precio_tarjeta,
        captura.tarjeta,
        int(captura.disponible),
    )
    if ultima is not None and tuple(ultima) == nuevo:
        return False

    con.execute(
        """
        INSERT INTO historico_precios (producto_id, precio_internet, precio_normal,
                                       precio_tarjeta, tarjeta_asociada, disponible)
             VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            producto_id,
            captura.precio_internet,
            captura.precio_normal,
            captura.precio_tarjeta,
            captura.tarjeta,
            int(captura.disponible),
        ),
    )
    return True


def minimo_historico(
    con: sqlite3.Connection, producto_id: int, ventana_dias: int
) -> int | None:
    """El precio más bajo vigente en los últimos `ventana_dias` días.

    No basta con mirar las filas dentro de la ventana: como solo se guardan
    variaciones, un precio fijado antes del inicio de la ventana y nunca
    cambiado no tiene ninguna fila dentro, y aun así es el precio vigente. Por
    eso se une la última fila anterior al corte.
    """
    ventana = f"-{int(ventana_dias)} days"
    fila = con.execute(
        """
        SELECT MIN(p) AS minimo FROM (
            SELECT precio_internet AS p
              FROM historico_precios
             WHERE producto_id = :pid
               AND capturado_el >= datetime('now', :ventana)
            UNION ALL
            SELECT p FROM (
                SELECT precio_internet AS p
                  FROM historico_precios
                 WHERE producto_id = :pid
                   AND capturado_el < datetime('now', :ventana)
                 ORDER BY capturado_el DESC, id DESC
                 LIMIT 1
            )
        )
        """,
        {"pid": producto_id, "ventana": ventana},
    ).fetchone()
    return fila["minimo"]


def dias_de_historico(con: sqlite3.Connection, producto_id: int) -> float:
    """Cuántos días hace que se vigila este producto. Cero si no hay histórico."""
    fila = con.execute(
        """
        SELECT (julianday('now') - julianday(MIN(capturado_el))) AS dias
          FROM historico_precios
         WHERE producto_id = ?
        """,
        (producto_id,),
    ).fetchone()
    return float(fila["dias"]) if fila["dias"] is not None else 0.0


def ultima_alerta(con: sqlite3.Connection, producto_id: int, regla: str):
    """La última alerta enviada para ese producto y esa regla, si la hubo."""
    return con.execute(
        """
        SELECT precio_notificado,
               (julianday('now') - julianday(enviado_el)) AS dias_desde
          FROM registro_alertas
         WHERE producto_id = ? AND regla = ?
         ORDER BY enviado_el DESC, id DESC
         LIMIT 1
        """,
        (producto_id, regla),
    ).fetchone()


def registrar_alerta(
    con: sqlite3.Connection, producto_id: int, regla: str, precio: int
) -> None:
    con.execute(
        """
        INSERT INTO registro_alertas (producto_id, regla, precio_notificado)
             VALUES (?, ?, ?)
        """,
        (producto_id, regla, precio),
    )
