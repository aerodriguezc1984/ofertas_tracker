# Etapa 3 — Emparejado: el mismo producto, más barato en otra parte

Fecha: 2026-10-07
Estado: aprobado el diseño en conversación; pendiente de revisión de este documento.
Etapas anteriores: `2026-10-04-esqueleto-design.md`, `2026-10-04-etapa-2-falabella-design.md` y
`2026-10-05-etapa-2b-solotodo-design.md`, las tres terminadas y fusionadas (`7f30c76`, 142 pruebas).

## Lo que la sonda cambió, antes de nada

Igual que en la 2b, se sondeó antes de diseñar. Tres resultados mandan sobre el resto del documento.

**1. Hoy no hay ni un emparejamiento, y es estructural.** Sobre la base real: 39 productos, 15 con
`producto_solotodo`, y **cero identificadores compartidos por dos filas**. `ean` está vacío en los
39, porque ni Paris ni Falabella lo publican en su JSON-LD. La causa es la exclusión de la 2b: el
identificador lo tienen justo las tiendas que **no** raspamos en directo, y no lo tienen las dos
que sí. El cruce más útil —«este notebook de Paris, ¿está más barato en otra parte?»— es
exactamente el que los datos de hoy no pueden tender.

**2. `external_url` no sirve como llave, y la API miente sobre ello.**

```
GET /entities/?external_url=https://www.paris.cl/notebook-...
→ 200 OK, count: 1701403
```

`external_url` no es un parámetro válido: la API lo **descarta en silencio** y devuelve el catálogo
entero, con el primer resultado apuntando a una tienda sin relación. Un 200 con datos no prueba que
el filtro filtre. Y aunque fuera válido, en Falabella la URL de SoloTodo no coincide carácter a
carácter con la nuestra.

**3. El SKU sí sirve, y el precio ajeno sale de una sola petición.**

| Sonda | Resultado |
|---|---|
| `entities/?stores=11&search=<sku>` (Paris) | `count: 1`, URL idéntica a la nuestra |
| `entities/?stores=9&search=<sku>` (Falabella) | `count: 1`, el producto correcto |
| `products/<id>/entities/` | 35 entidades, 3 con precio vigente, de tres tiendas distintas |

La última es la que define la etapa: **el precio del mismo artículo en todas las tiendas cuesta una
petición**. No hay que raspar nada para comparar.

## Alcance

### Dentro

- Resolver `producto_solotodo` para los productos que aún no lo tienen, a partir de `(tienda, sku)`.
- Un paso nuevo del ciclo que, para los productos vistos hoy, pide el precio del mismo artículo en
  todas las tiendas y decide si merece aviso.
- Una regla de aviso nueva, `mejor_precio`, con doble umbral —relativo y absoluto— y su cooldown.
- La segunda migración de esquema del proyecto: `productos.ultima_comparacion`.

### Fuera

- **Unificar el histórico.** El histórico y el mínimo siguen siendo **por tienda**. Un precio ajeno
  nunca entra en `historico_precios` ni mueve ningún mínimo. Decisión explícita del usuario.
- **Emparejar por título, marca o modelo.** Si SoloTodo no conoce el producto, no hay
  emparejamiento. Sin heurísticas, sin distancias de cadena, sin «probablemente es el mismo».
- **Guardar el catálogo ajeno.** Lo único que persiste de una comparación es la alerta.
- **Comprar.** El aviso lleva la URL de la tienda ajena y ahí termina su trabajo.

## Decisiones y su porqué

### El comparador es un paso aparte, después del ciclo

`ejecutar_ciclo` termina exactamente como hoy y después corre `ejecutar_comparacion`, que trabaja
sobre lo que acaba de quedar en la base.

Se descartaron dos alternativas. **Meterlo dentro de `_procesar`**, al capturar cada producto, daría
la máxima frescura, pero mete una petición de red en el bucle que hoy solo escribe en la base,
acopla el comparador a la captura, y un fallo de SoloTodo contaminaría el único camino que ya está
probado y funcionando. **Un comando suelto** no alargaría el ciclo, pero obliga a acordarse de
ejecutarlo y las alertas llegarían a destiempo respecto a las de bajada de precio.

Como paso separado, la comparación puede fallar entera sin arrastrar nada: si SoloTodo está caído,
se registra un aviso y el ciclo da por bueno lo que capturó.

### Solo se compara lo visto en este ciclo

Un precio nuestro de hace cuatro días comparado contra uno ajeno de hoy produce avisos falsos en las
dos direcciones: ellos bajaron, o nosotros subimos y no lo sabemos. Si un producto no se refrescó
hoy —porque su tienda falló, o porque salió de los resultados de búsqueda— no se compara.

El criterio es comprobable, no de apreciación: `ejecutar_comparacion` recibe la marca de tiempo
con la que arrancó el ciclo y selecciona los productos cuya `ultima_revision` es igual o posterior.
La columna ya existe y ya se actualiza en cada alta.

Coste aceptado: una tienda caída deja sus productos sin comparar ese día. Es preferible a avisar
sobre un precio que ya no es el nuestro.

### El precio nuestro es `precio_internet`

El mismo que ya decide las alertas de bajada. **No** el de tarjeta: ese exige una tarjeta concreta
—la de la propia tienda— y no es comparable entre tiendas. Comparar un precio con tarjeta de Paris
contra uno sin tarjeta de Winpy diría que Paris gana cuando no es verdad para quien no tiene esa
tarjeta.

### Todo precio ajeno sale de SoloTodo, y va etiquetado

Incluidos los de Paris y Falabella, que sí raspamos. No se mezclan fuentes dentro de un mismo
aviso: una comparación entre un precio nuestro y uno ajeno ya tiene una asimetría, y meter tres
orígenes distintos la haría ilegible.

**Esto merece decirse claro porque es confuso:** `solotodo.tiendas_excluidas` gobierna la
**captura**, no la comparación. SoloTodo sigue sin poder escribir una fila de Paris, y sigue
pudiendo decirnos que Paris lo tiene más barato. Son dos permisos distintos sobre la misma tienda,
y confundirlos es lo que haría crecer el histórico una fila por ciclo —
ver `2026-10-05-etapa-2b-solotodo-design.md`, «SoloTodo excluye las tiendas que ya cubrimos».

El aviso dice de dónde sale cada precio. El nuestro es nuestro y es de hoy; el ajeno es de SoloTodo
y puede ir rezagado.

### Una oferta sin stock no cuenta

`active_registry.is_available` falso descarta la entidad. Un precio más bajo de algo agotado es
ruido, y en la sonda las tres entidades activas del producto de prueba venían con `is_available`
en falso: no es un caso raro.

### La identidad exige coincidencia de SKU, no solo un resultado único

Para resolver `producto_solotodo` se pide `entities/?stores=<id>&search=<sku>`. En las cuatro
sondas devolvió exactamente un resultado. **Un solo resultado no basta como prueba de identidad:**
se exige además que el `sku` de la entidad coincida con nuestro `sku_externo`. Si no coincide, no se
asigna nada y se registra un WARNING.

Es el mismo criterio que ya rige en Falabella, donde el anclaje por SKU es lo que impide que el
precio del producto de al lado se cuele en la ficha vigilada. Y es el mismo principio que
«un precio adivinado no alerta ni entra al histórico», subido un nivel: **una identidad adivinada
es peor que un precio adivinado**, porque un precio malo contamina un ciclo y una identidad mala
contamina todas las comparaciones futuras de esa fila.

La correspondencia entre nuestro nombre de tienda y el identificador numérico de SoloTodo sale del
catálogo `/stores/` que la fuente ya pide y cachea, normalizado con `identificador_de_tienda`, que
ya existe.

### Resuelta una vez, no se vuelve a pedir

`producto_solotodo` no cambia. Una vez asignado, esa petición no se repite nunca.

Esto es cierto solo si la identidad llega a resolverse. Si `identidad_de` devuelve `None` —el SKU
no coincide, o SoloTodo no conoce el producto—, no queda ningún registro de que ya se intentó: el
producto vuelve a preguntarse en el turno siguiente, y en el siguiente, mientras siga sin resolver.
No es «una petición por producto en toda la vida del producto»; es una petición **por turno**
mientras no resuelva. Arreglarlo de verdad exigiría una columna nueva —y por tanto una tercera
migración— para distinguir «no se ha intentado» de «se intentó y no resolvió», y queda fuera de
esta etapa.

### El aviso exige los dos umbrales, no uno

```yaml
comparacion:
  activa: true
  caida_minima_pct: 10
  ahorro_minimo_pesos: 10000
  maximo_por_ciclo: 25
  cooldown_dias: 5
```

Avisa cuando la oferta es **al menos un 10 % más barata Y ahorra al menos 10.000 pesos**. Cada
condición tapa el agujero de la otra:

| Sin la condición | El agujero |
|---|---|
| absoluta | un mouse de 8.000 pesos avisa por 800 de diferencia |
| relativa | un notebook de 900.000 avisa por 10.000, que no mueve ninguna decisión |

El porcentaje es el único flotante del flujo, y solo se compara — nunca se guarda ni se usa para
calcular un precio. El ahorro en pesos es `int`, como todo el dinero del proyecto.

### El cooldown reutiliza lo que ya existe

`registrar_alerta` y `ultima_alerta` ya aceptan un nombre de regla. La comparación usa
`mejor_precio` y hereda el cooldown sin una tabla nueva ni una columna nueva. Un producto que ya
avisó no vuelve a avisar en `cooldown_dias`, aunque la diferencia siga ahí.

### `maximo_por_ciclo` y la columna que lo hace posible

Comparar cuesta una petición por producto y por ciclo, al ritmo lento de siempre. Con 39 productos
son unos tres minutos; crece en línea recta con cada producto que descubren las búsquedas, así que
el tope va en la configuración.

Con un tope hace falta decidir **a quién le toca**, y hacerlo al azar o por `id` dejaría productos
sin comparar nunca. Se comparan los que lleven más tiempo sin comparar, lo que exige una columna
nueva: `productos.ultima_comparacion`, `TEXT`, nulable.

Es la **segunda migración** del proyecto, y se escribe con lo que costó la primera:

> `CREATE TABLE IF NOT EXISTS` no lleva una columna nueva a una base que ya existe, y **ninguna
> prueba pasa por el camino de la migración**, porque todas crean la base desde cero. Además
> `ALTER TABLE ... ADD COLUMN` no admite `UNIQUE`, y solo admite `NOT NULL` con `DEFAULT`: sin él se
> acepta sobre una tabla vacía y se rechaza sobre una con filas, así que una declaración mal formada
> pasaría la suite entera y solo reventaría sobre la base real.
>
> `TEXT` nulable no toca ninguno de esos límites. Y la comprobación sobre la base real es
> irrepetible: **hay que copiarla antes de abrirla**, y anotar los recuentos de antes y después.

## Arquitectura

| Archivo | Responsabilidad |
|---|---|
| `src/nucleo/comparacion.py` | **nuevo** — `OfertaAjena`, `VeredictoMejorPrecio`, `mejor_oferta(...)`. Puro |
| `src/fuentes/solotodo.py` | + `identidad_de(tienda, sku)` y `ofertas_de(producto_solotodo)` |
| `src/almacen/esquema.sql` | + `productos.ultima_comparacion` |
| `src/almacen/conexion.py` | + la entrada en `COLUMNAS_NUEVAS` |
| `src/almacen/operaciones.py` | + `productos_a_comparar`, `guardar_identidad`, `marcar_comparado` |
| `src/avisos/base.py` | + el mensaje de `mejor_precio` |
| `runner.py` | + `ejecutar_comparacion`, llamada tras `ejecutar_ciclo` |
| `config/config.yaml` | + la sección `comparacion` |
| `herramientas/sonda_comparacion.py` | **nueva** — sonda manual contra la API real |

Las capas no cambian: `nucleo` sigue sin importar `sqlite3`, `requests` ni `almacen`, y `fuentes`
sigue sin importar `sqlite3`. `tests/test_capas.py` lo vigila y debe seguir en verde.

### Los dos tipos

```python
@dataclass(frozen=True)
class OfertaAjena:
    tienda: str          # nombre real de la tienda, ya normalizado
    precio: int          # pesos chilenos, nunca float
    url: str
    disponible: bool

@dataclass(frozen=True)
class VeredictoMejorPrecio:
    oferta: OfertaAjena
    ahorro: int          # pesos
    porcentaje: float    # solo para el texto del aviso y la comparación
```

`mejor_oferta(precio_nuestro, ofertas, reglas)` devuelve un `VeredictoMejorPrecio` o `None`. Sin
red, sin SQL, sin reloj: se prueba entera con listas construidas a mano.

## Flujo de una comparación

1. `ejecutar_comparacion` pide a `almacen` los productos **vistos en este ciclo**, ordenados por
   `ultima_comparacion` más antigua primero, como mucho `maximo_por_ciclo`.
2. Para cada uno sin `producto_solotodo`: `identidad_de(tienda, sku)`. Si el SKU no coincide, se
   registra y se pasa al siguiente. Si coincide, se guarda y no se vuelve a pedir.
3. `ofertas_de(producto_solotodo)` → lista de `OfertaAjena`, descartando las sin stock y la de
   nuestra propia tienda.
4. `mejor_oferta(precio_nuestro, ofertas, reglas)` decide. Si no hay veredicto, se marca como
   comparado y se sigue.
5. Si hay veredicto y el cooldown lo permite, se manda el aviso y **solo entonces** se registra la
   alerta. El orden importa: registrar antes de enviar dejaría un aviso perdido contando como
   enviado.
6. Se marca `ultima_comparacion` también si la petición de `ofertas_de` falla con una excepción
   inesperada (un `JSONDecodeError` sobre un 200 que no es JSON, un `AttributeError` si la API
   cambia de forma). `identidad_de` y `ofertas_de` ya atrapan `TiendaBloqueada` por dentro y
   devuelven `None` / `[]`, así que un bloqueo o una caída de red transitorios nunca llegan a este
   punto: siguen el camino normal y ya se marcan ahí arriba. Lo que llega aquí es, por descarte,
   persistente — se repetirá igual mañana —, y no marcarlo formaría un trinquete: combinado con
   `ORDER BY ultima_comparacion ASC`, el producto roto se quedaría para siempre en la cabecera de
   la cola, robándoles el turno a los demás.

## Errores

Tres niveles, de dentro afuera:

- **Una entidad malformada** dentro de `ofertas_de` se descarta con WARNING; las demás siguen.
- **Un producto** cuya petición falla se registra con `exc_info`, **se marca como comparado** y el
  bucle continúa con el siguiente. Marcarlo parece contraintuitivo —lo natural sería reintentarlo
  cuanto antes— y es justo lo que evita un trinquete: como el orden pone los no marcados primero,
  un producto que falla de forma persistente conservaría la cabecera para siempre y robaría un
  turno de modo acumulativo, hasta dejar sin comparar a todos los sanos. Y lo que llega aquí **es**
  persistente: los fallos transitorios no pasan por este camino, porque `identidad_de` y
  `ofertas_de` capturan `TiendaBloqueada` por dentro y devuelven vacío.
- **SoloTodo entero caído** deja el paso en cero comparaciones, con un WARNING, y `main` devuelve
  éxito igualmente: la captura de este ciclo es válida y ya está guardada.

Se mantiene la convención del proyecto: las fuentes capturan `TiendaBloqueada` y dejan escapar lo
demás, que el orquestador recoge con traza. Revisada y confirmada en la 2b.

## Pruebas

Ninguna toca la red. Contando desde las 142 actuales:

| Bloque | Qué fija |
|---|---|
| `test_comparacion.py` | la decisión pura: los dos umbrales por separado y juntos, el empate, la lista vacía, la oferta sin stock, la oferta más cara |
| `test_solotodo.py` | `identidad_de` con SKU que coincide y que no; `ofertas_de` sobre una fixture real; la entidad malformada |
| `test_operaciones.py` | `productos_a_comparar` respeta el ciclo y el orden; `marcar_comparado`; la migración de la columna nueva |
| `test_runner.py` | el paso completo con fuente falsa: avisa, respeta el cooldown, respeta el tope, y sobrevive a que SoloTodo falle |
| `test_capas.py` | sin cambios, debe seguir en verde |

Cada prueba nueva se valida rompiendo a propósito lo que dice medir, y comprobando que se pone roja
**por el motivo correcto** — no basta el rojo: si el mensaje de fallo no se parece al daño que
describe el docstring, la mutación o la prueba están mal.

## Criterios de éxito

1. La suite en verde, ninguna prueba toca la red.
2. Sobre la base real, copiada antes: la columna nueva aparece y los recuentos de productos e
   histórico no cambian.
3. Un ciclo real resuelve `producto_solotodo` para productos de Paris y Falabella, que hoy son 24
   sin identificador.
4. La comparación produce al menos un veredicto, o explica por qué no lo produjo.
5. Una segunda pasada **no** manda el mismo aviso, por el cooldown.
6. El histórico no gana ninguna fila por culpa de la comparación.

## Riesgos conocidos

| Riesgo | Qué pasa | Qué lo acota |
|---|---|---|
| El precio de SoloTodo va rezagado | Un aviso sobre un precio que ya subió | El aviso dice que el precio es de SoloTodo y lleva la URL para comprobarlo |
| `search=<sku>` devuelve más de un resultado | No se resuelve la identidad | La guarda de SKU: sin coincidencia exacta, no se asigna |
| SoloTodo cambia la forma de `products/<id>/entities/` | El paso entero falla | Falla ruidoso, con traza, y la captura del ciclo no se ve afectada |
| El tope deja productos sin comparar | Algunos tardan varios ciclos en compararse | El orden por `ultima_comparacion` garantiza que todos llegan |
| Una tienda ajena con precio absurdo (1 peso) | Un aviso falso | No se acota en esta etapa. Se registra como limitación conocida |

## Siguiente paso

Etapa 4 — operación: Excel, rotación de logs y Programador de tareas.
