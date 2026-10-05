# Rastreador de ofertas — Etapa 1: el esqueleto que camina

Fecha: 2026-10-04
Estado: aprobado. Enmendado el mismo día tras sondear las tiendas.

## Enmienda del 2026-10-04

Este documento se escribió dando por supuestas dos cosas que la sonda desmintió:

1. **Mercado Libre no es accesible.** Su API responde 403
   `PA_UNAUTHORIZED_RESULT_FROM_POLICIES` a toda petición anónima, y su web devuelve una
   página puente sin contenido a un cliente HTTP. Sin credenciales OAuth o sin navegador no
   hay lectura posible, así que **deja de ser la fuente de la Etapa 1**.
2. **VTEX no es la plataforma común del retail chileno.** Paris y Falabella corren sobre
   Next.js y abc.cl (la fusión de La Polar y AbcDin) sobre Salesforce Commerce Cloud. El
   adaptador VTEX habría cubierto mucho menos de lo previsto.

Lo que sí se verificó, con una petición normal y sin truco alguno: **Paris sirve su ficha
de producto con JSON-LD legible** (nombre, SKU y precio), y su página de búsqueda
`paris.cl/search?q=` devuelve enlaces a fichas. Falabella y abc.cl también publican
JSON-LD, lo que abarata la Etapa 2.

En consecuencia, **la fuente de la Etapa 1 es Paris por raspado**, y el **descubrimiento
por palabra clave entra en la Etapa 1** en vez de esperar a la Etapa 3: la búsqueda es una
página más que raspar, y el usuario la pidió expresamente. Lo que sigue en la Etapa 3 es el
emparejado del mismo producto entre tiendas distintas, que es el problema difícil.

Todo lo demás del documento —interfaz de fuente, esquema, histórico de variaciones,
arranque en frío, control de frecuencia, criterios de éxito— se mantiene intacto.

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
- Descubrimiento por palabra clave en esa misma tienda.
- Una fuente: Paris, leída raspando el JSON-LD de sus fichas.
- Histórico de precios en SQLite, registrando **variaciones**, no pasadas.
- Reglas por producto: precio máximo, descuento mínimo contra el mínimo histórico,
  exclusión de precios que exigen tarjeta de la casa.
- Alerta con control de frecuencia, por Telegram o a archivo.

### Fuera (etapas posteriores)

- Etapa 2 — anchura: Falabella y abc.cl con el mismo normalizador, SoloTodo, y la matriz
  de tres precios (que no viene en el JSON-LD y exige leer los datos de Next.js).
  **Dos deudas que la revisión final de la Etapa 1 dejó anotadas y que la Etapa 2 debe pagar
  antes de escribir la segunda tienda, no después de la tercera:**
  1. De las ~60 líneas de `fuentes/paris.py`, solo tres son propias de Paris: `BASE`, el
     patrón de enlace y la forma de la URL de búsqueda. El resto —el bucle de `obtener`, el
     manejo de `TiendaBloqueada`, el deduplicado, el corte por `limite`— se copiaría literal
     en cada tienda nueva y divergiría por separado. Extraer una `FuenteJsonLd` base
     parametrizada deja cada tienda en unas seis líneas, y es mucho más barato con una
     implementación que con tres.
  2. `registrar_si_cambio` compara `precio_tarjeta` pero no `tarjeta`: si cambia la tarjeta
     asociada y no su precio, no se anota fila. Hoy es latente porque Paris no publica
     ninguno de los dos; con la matriz de tres precios deja de serlo.
- Etapa 3 — emparejado de productos entre tiendas. Verificado que Paris no publica `gtin`,
  así que habrá que apoyarse en el parecido entre títulos (`rapidfuzz`) más que en el EAN.
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
por **plataforma técnica** y las tiendas se declaran en YAML. El motor de la Etapa 1 es el
**genérico de JSON-LD**, que no es propio de Paris: la misma pieza lee Falabella y abc.cl
en la Etapa 2. Lo único específico de Paris es la forma de su URL de búsqueda y la de sus
enlaces a ficha.

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
│   │   ├── transporte.py     # HTTP real: reintentos, ritmo lento
│   │   └── paris.py          # URL de búsqueda y forma de enlace de Paris
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
    def buscar(self, termino: str, limite: int) -> list[Captura]: ...
```

`buscar` devuelve capturas igual que `obtener`: en Paris la búsqueda da URLs de ficha y el
precio sale de cada una, así que cuesta una petición más las de los resultados. De ahí que
el límite por búsqueda sea configurable y conservador.

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
vigilados:
  - nombre: Home Panel Mónaco TV 55
    tienda: paris
    url: https://www.paris.cl/home-panel-monaco-tv-55-1-6-castano-off-white-MK2GCAHDUR.html
    reglas:
      precio_maximo: 200000
      descuento_minimo_pct: 15
      permitir_precio_tarjeta: false

busquedas:
  - termino: notebook 16gb
    tienda: paris
    reglas:
      precio_maximo: 400000
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
- `sqlite3.OperationalError` por base bloqueada: **no se reintenta.** El requisito original
  pedía un reintento, pero con WAL y un único proceso escritor no hay escenario que lo
  provoque, y un reintento que nunca se ejecuta es código que nadie puede probar ni mantener.
  Vuelve a la mesa en la Etapa 4, si el Programador de tareas llegara a solapar dos pasadas.
- El notificador de Telegram que falla no debe perder el dato: la alerta ya está en el
  histórico y el fallo se registra; no se marca como enviada, así que el siguiente ciclo
  lo reintenta.

## Pruebas

`pytest`. **Ninguna prueba toca la red.** Las fuentes reciben su transporte por inyección y
las pruebas pasan uno falso. Las *fixtures* son recortes: el bloque JSON-LD real de una
ficha de Paris y una página de búsqueda con su misma forma de enlace. Las páginas enteras
pesan de 2 a 4 MB y no tiene sentido versionarlas.

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
4. Si Paris devuelve error, el proceso termina con código 0, deja un `WARNING` en el log y
   no corrompe la base.

## Riesgos conocidos

**1. El raspado se rompe cuando la tienda cambia su página.** Es el riesgo estructural de
leer HTML en vez de una API: el día que Paris cambie la forma de sus enlaces o deje de
publicar JSON-LD, la fuente dejará de devolver capturas. Se mitiga de dos maneras: el
normalizador es genérico, de modo que un cambio de maquetación no lo afecta mientras siga
habiendo JSON-LD; y hay una sonda manual (`herramientas/sonda_paris.py`) que comprueba
contra la tienda real si las *fixtures* siguen pareciéndose a la realidad. Cuando la sonda
falle, **el fallo está en la página, no en las pruebas**: no se tocan las pruebas para que
pasen.

**2. Una lista de deseos larga multiplica las peticiones.** Con pausas de 2 a 5 segundos,
cien productos son entre tres y ocho minutos por pasada. Aceptable para uso personal; si
crece, la Etapa 4 tendrá que agrupar por lotes.

**3. El precio con tarjeta no siempre se distingue en los datos.** Algunas tiendas no
marcan qué medio de pago exige su precio destacado. Cuando no se pueda determinar,
`precio_tarjeta` queda a `None` y el precio se trata como `precio_internet`: es la lectura
conservadora, y como mucho hace que una oferta pase desapercibida en vez de avisar de una
que no puedes pagar.

**4. El JSON-LD de Paris no trae todo lo que querríamos.** Verificado: no publica `gtin`
(sin código de barras, el emparejado de la Etapa 3 dependerá del parecido entre títulos),
no declara `availability` (si la tienda no dice nada se asume disponible, porque lo
contrario silenciaría todas las alertas) y trae **un solo precio**, de modo que la matriz
de tres precios con el de tarjeta queda para la Etapa 2.

## Siguiente paso

Plan de implementación en `docs/plans/2026-10-04-etapa-1-esqueleto.md`.
