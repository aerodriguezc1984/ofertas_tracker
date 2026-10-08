-- Toda columna que se añada aquí hay que añadirla también a mano en
-- `COLUMNAS_NUEVAS` (almacen/conexion.py), para que una base ya creada la
-- reciba por migración; `CREATE TABLE IF NOT EXISTS` no la lleva a una base
-- existente. Ninguna prueba lo vigila: todas crean la base desde cero.
CREATE TABLE IF NOT EXISTS productos (
    id              INTEGER PRIMARY KEY,
    tienda          TEXT    NOT NULL,
    sku_externo     TEXT    NOT NULL,
    ean             TEXT,
    producto_solotodo INTEGER,
    titulo          TEXT    NOT NULL,
    url             TEXT    NOT NULL UNIQUE,
    imagen_url      TEXT,
    creado_el       TEXT    NOT NULL DEFAULT (datetime('now')),
    ultima_revision TEXT,
    ultima_comparacion TEXT,
    UNIQUE (tienda, sku_externo)
);

CREATE TABLE IF NOT EXISTS historico_precios (
    id               INTEGER PRIMARY KEY,
    producto_id      INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    precio_normal    INTEGER,
    precio_internet  INTEGER NOT NULL,
    precio_tarjeta   INTEGER,
    tarjeta_asociada TEXT,
    disponible       INTEGER NOT NULL DEFAULT 1,
    capturado_el     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS registro_alertas (
    id                INTEGER PRIMARY KEY,
    producto_id       INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    regla             TEXT    NOT NULL,
    precio_notificado INTEGER NOT NULL,
    enviado_el        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_hist_prod_fecha
    ON historico_precios (producto_id, capturado_el DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_prod_regla
    ON registro_alertas (producto_id, regla, enviado_el DESC);
