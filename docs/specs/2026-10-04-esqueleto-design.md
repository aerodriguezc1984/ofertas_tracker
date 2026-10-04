# Rastreador de ofertas — Etapa 1: el esqueleto que camina

Fecha: 2026-10-04
Estado: aprobado el diseño en conversación; pendiente de revisión de este documento.

## Por qué existe este documento

El plan original describía seis fases que cubrían cuatro subsistemas independientes
(extracción multi-tienda, emparejado de productos entre tiendas, motor de reglas sobre
histórico, y notificación con control de frecuencia). Construirlos en capas horizontales
—primero toda la base de datos, luego todos los extractores, luego las alertas— deja el
sistema inservible hasta el último día y obliga a diseñar el emparejado de productos a
ciegas, sin datos reales con los que contrastarlo.

Este documento especifica en su lugar una **vertical fina y completa**: una sola tienda,
de punta a punta, hasta que suene el teléfono. Es la Etapa 1 de cuatro.

## Alcance

### Dentro

- Lista de deseos: el usuario declara los productos concretos que quiere vigilar.
- Una fuente: Mercado Libre Chile.
- Histórico de precios en SQLite, registrando **variaciones**, no pasadas.
- Reglas por producto: precio máximo, descuento mínimo contra el mínimo histórico,
  exclusión de precios que exigen tarjeta de la casa.
- Alerta con control de frecuencia, por Telegram o a archivo.

### Fuera (etapas posteriores)

- Etapa 2 — anchura: adaptador de catálogo VTEX, lector genérico de JSON-LD, SoloTodo.
- Etapa 3 — descubrimiento: búsqueda por palabra clave y emparejado de productos entre
  tiendas (EAN cuando exista, `rapidfuzz` sobre el título cuando no).
- Etapa 4 — operación: reporte Excel, rotación de logs, Programador de tareas de Windows.

El diseño de la Etapa 1 se juzga, en parte, por lo barato que haga la Etapa 2. De ahí que
la interfaz de fuente sea la pieza más cuidada del documento, pese a que hoy solo tenga
una implementación.

## Decisiones y su porqué

### No se evade la detección de robots

Se usan catálogos y APIs públicas, con ritmo lento y cabeceras honestas. Cuando una tienda
bloquee, su adaptador queda marcado como no disponible en el log y el ciclo continúa con
las demás. Se descartó `playwright-stealth` con rotación de *User-Agent*: va contra los
términos de servicio de esas tiendas, se rompe con cada actualización de su defensa, y con
una docena de tiendas el coste de mantenimiento se multiplica por doce. Perder dos tiendas
es barato; mantener evasión en quince, no.

### Código por plataforma, no por tienda

El plan proponía un módulo Python por tienda. No escala a «todo el retail chileno»: quince
tiendas serían quince archivos que se rompen por separado. En su lugar se escribe un motor
por **plataforma técnica** y las tiendas se declaran en YAML. Hoy solo existe el motor de
Mercado Libre; la interfaz está diseñada para que VTEX, el lector genérico de JSON-LD y
SoloTodo entren después sin tocar el núcleo.

### El dinero es entero

Todos los precios se guardan y se operan como `int` de pesos chilenos. El peso no tiene
decimales y los flotantes solo aportan errores de redondeo en las comparaciones.

### El histórico registra cambios, no pasadas

El plan insertaba una fila por producto y ejecución. A seis pasadas diarias eso son miles
de filas idénticas que entierran las variaciones reales y engordan la base sin aportar
información. Aquí se inserta en `historico_precios` **solo cuando cambia** el precio o la
disponibilidad respecto de la última captura conocida; el hecho de haber mirado se anota
actualizando `productos.ultima_revision`.

**Consecuencia que la implementación debe respetar:** el mínimo de los últimos 90 días no
es `MIN(precio) WHERE capturado_el > hace_90_dias`. Si un precio se fijó hace 100 días y
nunca cambió, no hay ninguna fila dentro de la ventana y esa consulta no devuelve nada. El
mínimo correcto es el menor entre las filas de la ventana **y la última fila anterior al
inicio de la ventana** (el precio que estaba vigente al abrirse). Hay una prueba
específica para esto.

### Guarda de arranque en frío

La fórmula de descuento del plan compara el precio actual contra el mínimo histórico. El
primer día, todo precio es su propio mínimo, y un producto recién añadido dispararía una
alerta de descuento falsa. Por eso la regla de descuento no se evalúa hasta que el producto
acumule `dias_minimos_para_descuento` días de histórico (7 por defecto). Antes de eso solo
se evalúan reglas de precio absoluto, que no dependen del pasado.

## Arquitectura

```
ofertas_tracker/
├── config/
│   ├── config.yaml           # ritmos, ventanas, umbrales
│   └── lista_deseos.yaml     # los productos vigilados y sus reglas
├── .env                      # secretos; nunca versionado
├── .env.example              # plantilla sin valores
├── src/
│   ├── almacen/
│   │   ├── esquema.sql
│   │   ├── conexion.py       # SQLite en modo WAL
│   │   └── operaciones.py    # alta de producto, registro de cambio, consultas
│   ├── fuentes/
│   │   ├── base.py           # Captura, Referencia, protocolo Fuente
│   │   └── mercadolibre.py
│   ├── nucleo/
│   │   ├── normalizador.py   # respuesta cruda -> Captura
│   │   └── evaluador.py      # reglas y descuento contra histórico
│   └── avisos/
│       ├── base.py           # protocolo Notificador
│       ├── archivo.py        # escribe logs/alertas.jsonl
│       └── telegram.py
├── tests/
│   └── fixtures/             # respuestas reales grabadas, en JSON
├── logs/
├── data/
└── runner.py
```

Cada módulo tiene una responsabilidad y se puede probar solo. `nucleo` no sabe de HTTP;
`fuentes` no sabe de SQLite; `avisos` no sabe de reglas.

### La interfaz de fuente

Es el contrato que hace barata la Etapa 2. Toda fuente devuelve el mismo objeto, venga de
una API REST, de un catálogo VTEX, de un `<script type="application/ld+json">` o de un
agregador:

```python
@dataclass(frozen=True)
class Captura:
    tienda: str
    sku_externo: str
    titulo: str
    url: str
    precio_internet: int            # CLP, lo paga cualquiera
    precio_normal: int | None       # el tachado, si lo hay
    precio_tarjeta: int | None      # exige tarjeta de la casa
    tarjeta: str | None             # 'CMR', 'CENCOSUD', 'RIPLEY'…
    disponible: bool
    imagen_url: str | None = None
    ean: str | None = None          # lo aprovechará la Etapa 3

@dataclass(frozen=True)
class Referencia:
    """Lo que la lista de deseos entrega a una fuente: qué mirar y dónde."""
    tienda: str
    url: str
    sku_externo: str | None = None   # si falta, la fuente lo deduce de la url

class Fuente(Protocol):
    nombre: str
    def obtener(self, referencias: list[Referencia]) -> list[Captura]: ...
```

`buscar(termino, limite)` se añadirá al protocolo en la Etapa 3. No se declara ahora: un
método que nadie implementa es deuda, no previsión.

El resto del sistema no sabe de qué tienda viene un dato. Una fuente que no pueda
determinar `precio_internet` no devuelve la captura: devolver un cero sería inventarse una
oferta.

## Modelo de datos

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS productos (
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
```

Diferencias respecto del esquema del plan, y por qué:

- **`id INTEGER` en vez de `MD5(tienda + sku)`.** La identidad real del producto es el par
  `(tienda, sku_externo)` y eso se expresa con un `UNIQUE`. El hash no añade garantías y
  vuelve ilegible cualquier consulta hecha a mano sobre la base.
- **`reglas_filtro` no es una tabla.** En la Etapa 1 las reglas viven junto al producto en
  `lista_deseos.yaml`, que es donde el usuario las edita. Una tabla de reglas sin interfaz
  para editarlas sería una capa de indirección sin usuario. Se reconsiderará en la Etapa 3,
  cuando las reglas dejen de estar atadas a un producto concreto.
- **`registro_alertas.regla` es texto, no una clave foránea**, por lo mismo.
- **Fechas como texto ISO (`datetime('now')`, UTC).** SQLite no tiene tipo fecha; dejarlo
  explícito evita comparaciones sorpresa.

## Configuración

`config/config.yaml` — versionado, sin secretos:

```yaml
ejecucion:
  espera_entre_peticiones_seg: [2, 5]   # pausa aleatoria en ese rango
  reintentos: 3                          # con espera creciente ante 429 y 5xx
historico:
  ventana_minimo_dias: 90
  dias_minimos_para_descuento: 7
alertas:
  canal: archivo                         # archivo | telegram
  cooldown_dias: 5
```

`config/lista_deseos.yaml`:

```yaml
- nombre: Notebook Lenovo ThinkPad E14
  url: https://articulo.mercadolibre.cl/MLC-XXXXXXXXX-...
  reglas:
    precio_maximo: 500000
    descuento_minimo_pct: 15
    permitir_precio_tarjeta: false
```

`.env`, excluido por `.gitignore`, con `.env.example` versionado como plantilla:

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ML_CLIENT_ID=
ML_CLIENT_SECRET=
```

Ningún secreto se escribe en el código ni en los logs. El notificador de Telegram, si el
token falta, falla con un mensaje claro al arrancar en lugar de a mitad del ciclo.

## Flujo de ejecución

`runner.py`:

1. Carga configuración y lista de deseos. Si un producto declara una regla desconocida,
   avisa y lo salta; no aborta.
2. Agrupa las referencias por fuente.
3. Por cada fuente, dentro de su propio `try/except`: captura con reintentos y espera
   creciente ante 429 y 5xx, con pausa aleatoria entre peticiones.
4. Normaliza a `Captura`.
5. Da de alta el producto si es nuevo; actualiza `ultima_revision`; inserta en
   `historico_precios` solo si el precio o la disponibilidad difieren de la última fila.
6. Evalúa las reglas del producto.
7. Consulta `registro_alertas` y decide si notifica.
8. Notifica y registra lo notificado.

### Reglas

- `precio_maximo`: se compara contra `precio_internet`, o contra `min(precio_internet,
  precio_tarjeta)` si `permitir_precio_tarjeta` es cierto.
- `descuento_minimo_pct`: `(minimo_historico - precio_actual) / minimo_historico * 100`,
  solo si el producto supera `dias_minimos_para_descuento`.
- Un producto con `disponible = 0` nunca alerta.

### Control de frecuencia

Se notifica si, y solo si, se cumple alguna de estas tres:

1. No hay ninguna alerta previa para ese producto y esa regla.
2. El precio actual es **menor** que `precio_notificado` de la última alerta.
3. Han pasado más de `cooldown_dias` desde la última alerta y el producto sigue cumpliendo
   la regla.

Un precio que sube, o que se queda igual, no vuelve a avisar.

## Errores

- Fallo de red, 5xx o tiempo agotado: se reintenta según configuración; agotados los
  reintentos, se registra `WARNING` nombrando la fuente y el ciclo **continúa con las
  demás**. Hay una prueba que lo verifica.
- Respuesta con forma inesperada: la captura se descarta con `WARNING` que nombra el campo
  ausente. Nunca se guarda un precio inventado.
- `sqlite3.OperationalError` por base bloqueada: WAL lo hace improbable; aun así, la
  escritura se reintenta una vez antes de propagar.
- El notificador de Telegram que falla no debe perder el dato: la alerta ya está en el
  histórico y el fallo se registra; no se marca como enviada, así que el siguiente ciclo
  lo reintenta.

## Pruebas

`pytest`. **Ninguna prueba toca la red.** Las respuestas reales de Mercado Libre se graban
una vez en `tests/fixtures/*.json` y las pruebas trabajan sobre ellas, de modo que la suite
corre sin conexión y no depende de que un producto siga en stock.

Cobertura mínima para dar la etapa por cerrada:

- **Almacén**: alta idempotente (capturar dos veces no duplica el producto); el histórico
  no crece si nada cambió; sí crece si cambia el precio; sí crece si cambia la
  disponibilidad.
- **Mínimo histórico**: el caso de la ventana, con un precio fijado antes de que empiece y
  sin filas dentro. Esta prueba debe fallar si se implementa con un `MIN` ingenuo.
- **Normalizador**: producto con descuento, sin descuento, sin stock, con precio de tarjeta,
  y respuesta a la que le falta el precio (se descarta).
- **Evaluador**: precio máximo con y sin tarjeta permitida; descuento por encima y por
  debajo del umbral; guarda de arranque en frío; producto sin stock.
- **Control de frecuencia**: dos pasadas idénticas producen **una** alerta; una bajada
  posterior produce otra; una subida no produce ninguna.
- **Aislamiento de fallos**: una fuente que lanza excepción no impide que otra complete.

Se sigue TDD: cada prueba se escribe antes que su implementación y se comprueba que falla
por la razón esperada antes de hacerla pasar.

## Criterios de éxito

La Etapa 1 está terminada cuando:

1. `pytest` pasa entero, sin conexión a internet.
2. `python runner.py` sobre una lista de deseos real guarda los productos la primera vez,
   y una segunda ejecución inmediata **no** añade filas al histórico ni envía alertas.
3. Una bajada de precio real o simulada produce exactamente una alerta.
4. Si Mercado Libre devuelve error, el proceso termina con código 0, deja un `WARNING` en
   el log y no corrompe la base.

## Riesgos conocidos

**1. El acceso a la API de Mercado Libre puede exigir autenticación.** El plan daba por
pública la ruta `api.mercadolibre.com/sites/MLC/search`. Mercado Libre ha ido cerrando el
acceso anónimo a sus endpoints, así que no se puede asumir que responda sin credenciales.
La primera tarea de la implementación es una **sonda** que lo compruebe. Si exige OAuth,
registras una aplicación gratuita en el portal de desarrolladores y sus credenciales van a
`.env`; si eso tampoco encaja, se adelanta el lector genérico de JSON-LD de la Etapa 2, que
lee la propia ficha del producto. El diseño no depende de cuál de las tres salga: las tres
cumplen la misma interfaz `Fuente`.

**2. Una lista de deseos larga multiplica las peticiones.** Con pausas de 2 a 5 segundos,
cien productos son entre tres y ocho minutos por pasada. Aceptable para uso personal; si
crece, la Etapa 4 tendrá que agrupar por lotes.

**3. El precio con tarjeta no siempre se distingue en los datos.** Algunas tiendas no
marcan qué medio de pago exige su precio destacado. Cuando no se pueda determinar,
`precio_tarjeta` queda a `None` y el precio se trata como `precio_internet`: es la lectura
conservadora, y como mucho hace que una oferta pase desapercibida en vez de avisar de una
que no puedes pagar.

## Siguiente paso

Plan de implementación detallado, con las tareas en orden y la sonda de Mercado Libre como
primera de todas.
