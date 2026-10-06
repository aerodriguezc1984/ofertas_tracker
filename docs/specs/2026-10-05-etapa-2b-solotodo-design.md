# Etapa 2b — Anchura de verdad: SoloTodo

Fecha: 2026-10-05
Estado: aprobado el diseño en conversación; pendiente de revisión de este documento.
Etapas anteriores: `2026-10-04-esqueleto-design.md` y `2026-10-04-etapa-2-falabella-design.md`,
ambas terminadas y fusionadas (`b826415`, 111 pruebas).

## Lo que la sonda cambió, antes de nada

La Etapa 2 dejó escrito que la 2b sería «abc.cl y SoloTodo». Sondear SoloTodo **antes** de diseñar
—la lección que costó rehacer el ancla de la Etapa 1— desmintió esa forma:

- **SoloTodo no es una tienda que raspar: es una API REST pública** en `api.solotodo.com`,
  navegable, sin autenticación. Su `robots.txt` solo prohíbe `/search` **de la web**; la API vive en
  otro host y está hecha para consumirse.
- Expone **370 tiendas**, 70 categorías y **151.778 entidades activas** con precio, filtrables por
  tienda, categoría, palabra clave y disponibilidad. Los precios estaban al día el 2026-10-05.
- Y trae **`product`: la identidad normalizada del mismo artículo entre tiendas.** Comprobado: el
  producto 43835 aparece activo en tres tiendas a 49.990, 34.900 y 55.900.

Esa última línea es la que reordena el proyecto. La Etapa 3 iba a atacar el emparejado entre
tiendas con parecido de títulos, que es una aproximación mala. SoloTodo lo trae resuelto.

**Consecuencia sobre el alcance:** raspar abc.cl da una tienda; una integración con esta API da
368 que no cubrimos (370 menos las dos que ya tenemos en directo). abc.cl sale de la etapa.

## Alcance

### Dentro

- Una fuente nueva, `SoloTodo`, que implementa el protocolo `Fuente` **sin heredar de
  `FuenteJsonLd`**.
- La columna `producto_solotodo` en `productos`, y **el primer mecanismo de migración del
  proyecto**, que es lo que la hace posible sobre una base que ya existe.
- La clave `fuente:` en la lista de deseos, para poder vigilar lo que se descubra por esta vía.

### Fuera

- **abc.cl.** Cubierto por SoloTodo como una más de las 368.
- **El emparejado entre tiendas.** Se guarda el dato que lo hará posible; no se construye nada
  encima. La Etapa 3 se rediseñará cuando haya meses de histórico con ese identificador dentro.
- **El precio con tarjeta de las tiendas que SoloTodo cubre.** No lo publica. Ver la limitación
  más abajo.

## Decisiones y su porqué

### SoloTodo no va sobre `FuenteJsonLd`

No lee HTML ni JSON-LD: consume JSON de una API. Heredar de la base para reutilizar un bucle que
descarga páginas y busca bloques `<script>` sería torcer la base para que quepa algo que no encaja.

La spec de la Etapa 2 ya lo previó: *«No es una jerarquía obligatoria. `Fuente` sigue siendo el
protocolo que define una fuente, y una tienda que no encaje en este molde puede implementarlo por
su cuenta.»* Esta etapa es la primera vez que esa previsión se cobra, y confirma que la frase valía
la pena.

### `tienda` es la tienda real, no «solotodo»

Una entidad de SoloTodo **está en AbcDin**. Guardarla con `tienda = "solotodo"` sería mentir en la
fila: el producto no se compra en SoloTodo, que es un agregador. SoloTodo es el *proveedor* del
dato, no el vendedor.

La identidad se construye con el nombre de la tienda normalizado: minúsculas, acentos resueltos, y
todo lo que no sea alfanumérico convertido en guion y colapsado. `AbcDin` → `abcdin`;
`PC Factory` → `pc-factory`.

### SoloTodo excluye las tiendas que ya cubrimos en directo

Verificado: para una entidad de Falabella, el `external_url` de SoloTodo es **exactamente la misma
URL** que usa nuestro adaptador directo, y su `sku` es el mismo número. Así que ambas fuentes
caerían en la misma fila de `productos` por el `UNIQUE (tienda, sku_externo)`.

Eso suena deseable y es una trampa, porque las dos fuentes **discrepan en precisión**: el adaptador
directo da tres precios con `tarjeta = "CMR"`, y SoloTodo da dos con `tarjeta = None`. Alternándose
sobre el mismo producto, `registrar_si_cambio` vería la tarjeta cambiar en cada pasada y anotaría
**una fila nueva por ciclo, para siempre**, sin que ningún precio se hubiera movido. El histórico
—la estructura más cara de reparar del proyecto— se llenaría de ruido indistinguible.

Hay un segundo motivo, independiente del primero: `productos.url` es `UNIQUE`. Aunque la identidad
`(tienda, sku_externo)` difiriera por cualquier motivo, dos filas con el mismo `external_url`
chocarían contra esa restricción y el alta lanzaría `IntegrityError`.

Así que SoloTodo es anchura y los adaptadores directos son profundidad, y **cada uno manda en lo
suyo**. La lista de tiendas excluidas vive en `config/config.yaml`, no incrustada en el código,
porque crece cada vez que se añada un adaptador directo.

La API permite *incluir* tiendas (`?stores=`) pero no excluirlas, así que el filtro se aplica del
lado del cliente, sobre los resultados.

### Los precios de SoloTodo están etiquetados

`normal_price` y `offer_price` vienen con nombre propio, así que `precios_etiquetados = True` y
estas capturas **no necesitan confirmación**. El mecanismo de la Etapa 2 sigue existiendo para
Falabella y no estorba aquí.

`precio_internet` ← `offer_price`; `precio_normal` ← `normal_price`; `precio_tarjeta` y `tarjeta`
quedan a `None`.

Los precios llegan como cadenas con dos decimales (`"587990.00"`). `a_entero` ya los resuelve
correctamente: su regla trata exactamente dos cifras tras el punto como decimales y redondea.

### El primer cambio de esquema del proyecto

`productos` gana `producto_solotodo INTEGER` (nulable). Y ahí aparece un problema que no existía:

**`abrir()` no sabe migrar.** Aplica el esquema con `CREATE TABLE IF NOT EXISTS`, así que sobre una
base que ya existe una columna añadida **nunca llega**. Y las pruebas no lo detectarían jamás,
porque cada una crea su base desde cero con `tmp_path`. El fallo solo aparecería en la base real
del usuario, con meses de histórico dentro.

Se resuelve con lo mínimo que funcione: tras aplicar el esquema, `abrir()` consulta
`PRAGMA table_info` de cada tabla y añade con `ALTER TABLE ... ADD COLUMN` las columnas declaradas
que falten. SQLite lo admite sin reescribir la tabla mientras la columna sea nulable o tenga un
valor por defecto constante, que es el caso.

> [!warning] La prueba que lo vigila
> Crear una base con el esquema **anterior**, meter una fila, abrirla con `abrir()`, y comprobar
> que la columna nueva existe **y que la fila sigue ahí**. Sin ese caso, el mecanismo de migración
> es código que nadie ha visto funcionar — y su único usuario es una base que no se puede repetir.

### La lista de deseos aprende a nombrar su fuente

Hoy el orquestador busca la fuente por el nombre de la tienda: `fuentes.get(vigilado["tienda"])`.
Con SoloTodo esos dos valores dejan de coincidir — un producto de `abcdin` se captura con la fuente
`solotodo` — así que una entrada puede declararlo:

```yaml
vigilados:
  - nombre: Notebook que vi en AbcDin
    tienda: abcdin
    fuente: solotodo
    url: https://api.solotodo.com/entities/1379496/
    reglas:
      precio_maximo: 400000
```

`fuente` es opcional y por defecto vale lo que `tienda`, así que todas las entradas existentes
siguen funcionando sin tocarlas.

La `url` de una entrada de SoloTodo es la de la **API**, no la de la tienda: es lo que `obtener`
necesita pedir. La URL de la tienda llega después, dentro de la captura, y es la que aparece en el
aviso.

## Arquitectura

```
src/fuentes/
├── solotodo.py        # NUEVO: la fuente, sin herencia
└── …                  # sin cambios
src/almacen/
├── esquema.sql        # + productos.producto_solotodo
├── conexion.py        # + la migración por columnas faltantes
└── operaciones.py     # `alta_o_actualiza_producto` guarda el identificador
runner.py              # resuelve `fuente:`, registra SoloTodo
config/config.yaml     # + solotodo.tiendas_excluidas
herramientas/
└── sonda_solotodo.py  # NUEVO: sonda manual contra la API real
```

## Flujo de una búsqueda

1. Una petición a `entities/?search=<término>&is_active=true`. Devuelve 100 entidades; con
   `limite_por_busqueda` en 15 basta una página.
2. La lista de tiendas (`stores/`) se pide **una vez** y se guarda en la propia instancia de la
   fuente, que vive lo que dura el ciclo: hacen falta sus nombres para construir el `tienda` de
   cada captura. Se pide de forma perezosa, en la primera búsqueda u `obtener` que la necesite, no
   al construir la fuente — así un ciclo sin búsquedas de SoloTodo no gasta ninguna petición.
3. Se descartan las entidades de las tiendas excluidas y las que no traen `active_registry`.
4. Cada entidad restante se convierte en `Captura`, ya etiquetada.
5. Desde ahí el camino es el de siempre: alta, mínimo, histórico, evaluación, frecuencia, aviso.

Coste: **dos peticiones por ciclo** (la lista de tiendas y la búsqueda), más una por cada vigilado
de SoloTodo.

## Errores

- La API no responde o devuelve 5xx: el transporte reintenta y, agotado, lanza `TiendaBloqueada`.
  La fuente lo registra y devuelve vacío, como cualquier otra.
- Una entidad sin `active_registry` se descarta en silencio: no es un error, es un producto que la
  tienda ya no ofrece.
- Una entidad cuya tienda no aparece en el catálogo cacheado se descarta con un `WARNING`. Sin
  nombre de tienda no hay identidad, y una identidad inventada mezcla productos — el mismo criterio
  que ya rige para un SKU ausente.

## Limitación conocida: sin precio de tarjeta

SoloTodo publica `normal_price` y `offer_price`, y nada más. Toda la matriz de tres precios que
construyó la Etapa 2 se pierde por esta vía.

No es un defecto que arreglar: es la diferencia entre anchura y profundidad. Una tienda que te
importe de verdad merece su adaptador directo; las otras 368 valen más cubiertas con dos precios
que no cubiertas.

Consecuencia concreta: `permitir_precio_tarjeta` no cambia nada en una regla aplicada a una captura
de SoloTodo, porque `precio_tarjeta` siempre es `None` y `precio_aplicable` cae en
`precio_internet`. Es el comportamiento correcto y conviene saberlo antes de extrañarse.

## Pruebas

`pytest`, **ninguna prueba toca la red**. Las respuestas reales de la API se graban recortadas como
*fixtures* JSON.

Cobertura mínima para cerrar la etapa:

- **Conversión**: una entidad activa da la `Captura` esperada, con `tienda` normalizada, los dos
  precios en su sitio, `precio_tarjeta` a `None` y `precios_etiquetados` a `True`.
- **Normalización del nombre**: `AbcDin` → `abcdin`, `PC Factory` → `pc-factory`.
- **Exclusión**: una entidad de una tienda excluida no produce captura.
- **Descartes**: sin `active_registry`, y con una tienda que no está en el catálogo (esta además
  deja `WARNING`).
- **`ean` ausente** llega como `None`, no como la cadena `"None"`.
- **Migración**: una base creada con el esquema anterior, con una fila dentro, gana la columna al
  abrirse y conserva la fila.
- **`fuente:`**: una entrada que la declara usa esa fuente; una que no, sigue usando su `tienda`.
- **Precios con decimales**: `"587990.00"` llega como `587990`, entero.

Cada prueba nueva se valida rompiendo a propósito lo que dice medir — y comprobando que se pone
roja **por el motivo correcto**, no solo que se pone roja.

## Criterios de éxito

1. `pytest` pasa entero, sin conexión.
2. `herramientas/sonda_solotodo.py` devuelve entidades reales con precio de tiendas que no sean
   Paris ni Falabella.
3. Un ciclo real captura productos de SoloTodo y guarda su `producto_solotodo`.
4. **La base existente del usuario se abre sin perder nada y gana la columna.**
5. Las sondas de Paris y Falabella siguen en verde: la fuente nueva no tocó a las que funcionaban.
6. `tests/test_capas.py` sigue en verde.

## Riesgos conocidos

**1. La identidad de la tienda depende de su nombre.** Si SoloTodo renombra «AbcDin», el
identificador cambia y sus productos se duplican en nuestra base. Usar su identificador numérico lo
evitaría, pero haría la configuración ilegible (`tienda: st30`). Se elige el nombre legible a
sabiendas; si alguna vez ocurre, se arregla con una tabla de alias.

**2. Las condiciones de uso de la API no están verificadas.** Es pública, navegable y sin
autenticación, y su `robots.txt` no la cubre. Aun así, la primera tarea de la implementación debe
buscar unas condiciones de uso o un límite de peticiones publicado, y dejar escrito lo que
encuentre. El ritmo del proyecto ya es bajo —dos peticiones por ciclo— pero «no encontré
condiciones» y «no las busqué» no son lo mismo.

**3. Se depende de la cobertura y la frescura de un tercero.** Si SoloTodo deja de actualizar una
tienda, lo pareceremos nosotros. `last_pricing_update` viene en cada entidad y permitiría avisar de
datos rancios; no entra en esta etapa, pero queda anotado.

## Siguiente paso

Plan de implementación, con la verificación de las condiciones de uso como primera tarea.
