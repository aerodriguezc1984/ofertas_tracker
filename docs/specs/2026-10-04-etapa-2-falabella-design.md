# Etapa 2 — Anchura: Falabella y la fuente base

Fecha: 2026-10-04
Estado: aprobado el diseño en conversación; pendiente de revisión de este documento.
Etapa anterior: `2026-10-04-esqueleto-design.md` (terminada, fusionada en `89c3dc1`).

## Qué entra y qué no

La Etapa 2 de la spec original listaba cuatro cosas. Entran dos, y por el mismo motivo:
**una segunda tienda es la que paga las deudas de la primera, y conviene pagarlas antes de que
haya tres.**

### Dentro

- **Extraer una fuente base** de la que `Paris` y `Falabella` sean casos finos.
- **Falabella**, con su matriz de tres precios (`cmrPrice` / `internetPrice` / `normalPrice`).
- **La deuda del histórico**: `registrar_si_cambio` compara también `tarjeta`, no solo su precio.

### Fuera, a una Etapa 2b

- **abc.cl.** Sin sondear. La lección de la etapa anterior es que una tienda sin sondear trae
  sorpresas propias, y Falabella ya ha traído cuatro.
- **SoloTodo.** No es una tienda sino un catálogo ya normalizado, y tensionará la interfaz
  `Fuente` de un modo que las tiendas no hacen. Merece su propio diseño.

Lo que esta etapa demuestra —o no— es que la fuente base generaliza. Si Falabella entra en seis
líneas, abc.cl será barato. Si hay que torcer la base para que quepa, es mejor saberlo con dos
tiendas que con cuatro.

## Lo que la sonda encontró

Verificado contra falabella.com el 2026-10-04, con el transporte del propio proyecto.

| | Página de búsqueda | Ficha de producto |
|---|---|---|
| Coste | **1 petición, 56 productos** | 1 petición, ~1,2 MB |
| Precios | 2 o 3 ofertas, **sin etiquetar** | `cmrPrice` / `internetPrice` / `normalPrice` explícitos |
| SKU | ausente; está en la URL (`/product/<id>/`) | `sellerSkuId` |
| Forma | `ItemList` con los productos dentro | varias listas `prices` por página |

Cuatro particularidades que el código actual no sobrevive:

1. **El JSON-LD viene escapado con entidades HTML** (`&quot;`), así que `json.loads` falla.
2. **Los productos están dentro de un `ItemList`**, no en el primer nivel.
3. **No hay `sku`** en los productos de la búsqueda.
4. **La ficha contiene varias listas `prices`** —las de los carruseles de promoción— y la primera
   suele ser de otro producto. Hay que anclar al `sellerSkuId` correcto.

La cuarta es la versión profunda del defecto I5 que cerró la etapa anterior: «el primer bloque gana»
es una suposición con forma de Paris.

### El dato que falta

De cuatro productos comparados, **tres coinciden exactamente** entre el orden de la búsqueda y las
etiquetas de la ficha, y **uno no**: su precio intermedio difiere (679.990 en la búsqueda,
619.990 de `internetPrice` en la ficha). O el anclaje al SKU tiene un fallo, o la discrepancia es
real. **La primera tarea de la implementación lo resuelve** sobre una muestra mayor, antes de
construir nada encima.

Las dos respuestas sirven: si es real, refuerza el diseño de abajo; si es un fallo de parseo, hay
que corregirlo antes de que se convierta en cimiento.

## Decisiones y su porqué

### Un precio inferido nunca dispara una alerta

El orden de las ofertas de la búsqueda es una inferencia (la más barata ascendente es la de
tarjeta, la más cara la tachada), y una inferencia que falle produce exactamente el peor aviso
posible: el que te manda a una tienda a pagar más de lo que decía.

Pero no hay que elegir entre inferir y pedir una ficha por resultado. **Solo los candidatos que ya
cumplen la regla merecen una ficha.** `limite_por_busqueda` (15 hoy) recorta primero, y de esos
quince suelen cumplir uno o dos: se pagan una o dos peticiones de confirmación, y ninguna alerta
sale de un dato adivinado.

El recorte por `limite` sucede **antes** de pagar ninguna ficha, que es lo que hace barata esta
vía: el `ItemList` trae 56 productos por una petición, se queda con quince, y solo los que
prometen algo cuestan una segunda.

`Captura` gana un campo:

```python
precios_etiquetados: bool = True
```

Las capturas que Falabella saca de su búsqueda lo traen en `False`. Paris no se entera: las suyas
vienen del JSON-LD de la ficha y el valor por defecto ya es el correcto.

### Un precio inferido tampoco entra en el histórico

Esta es la consecuencia que obliga a ordenar el flujo con cuidado, y no es obvia.

Si una captura inferida se guarda en `historico_precios`, su precio entra a formar parte del
mínimo histórico **para siempre**. Un dato adivinado contaminaría el cálculo que sostiene todas
las alertas de descuento del sistema, mucho después de que nadie recuerde de dónde salió.

Así que el orden en `_procesar` para una captura con `precios_etiquetados = False` es:

1. Evaluar las reglas contra el dato inferido. **Es solo un filtro barato**: no se escribe nada.
2. Si no cumple ninguna regla, se descarta entera. Ni alta, ni histórico, ni alerta.
3. Si cumple, se pide la ficha y se obtiene la captura exacta.
4. A partir de ahí se trata exactamente como cualquier otra captura: alta, mínimo, histórico,
   evaluación con el dato bueno, control de frecuencia, aviso.

Si la ficha no se puede leer, se registra un `WARNING` y se descarta. **Nunca se alerta ni se
escribe con el dato inferido.**

> Consecuencia aceptada: un producto que aparece en tus búsquedas semana tras semana sin cumplir
> nunca una regla no acumula histórico. Cuando por fin baje, no habrá mínimo con el que compararlo
> y solo valdrán las reglas de precio absoluto — que es justo lo que ya hace la guarda de arranque
> en frío para cualquier producto nuevo. Guardar un mínimo adivinado sería peor que no tenerlo.

### La fuente base se queda con el bucle, no con la expresión regular

La tentación es una base de «bucle más patrón de enlace». No sirve: la búsqueda de Falabella **ya
trae los productos dentro**, no enlaces que seguir. Una base que asuma «buscar devuelve enlaces»
excluye a Falabella del primer día.

Lo que de verdad se repite es el andamiaje: el bucle de `obtener`, el salto ante una tienda
bloqueada, el descarte de lo que no da datos utilizables, el deduplicado por URL conservando el
orden, el corte por `limite`, y los avisos. Eso sube a la base. Baja a cada tienda lo que de verdad
varía, en tres ganchos:

```python
@dataclass(frozen=True)
class Candidato:
    """Lo que una búsqueda encuentra: dónde mirar y lo que ya se sabe de ahí."""

    referencia: Referencia
    captura: Captura | None = None   # si la búsqueda ya trae el dato


class FuenteJsonLd:
    nombre: str
    BASE: str

    def __init__(self, transporte: Transporte) -> None: ...

    # Los tres ganchos que cada tienda implementa
    def url_de_busqueda(self, termino: str) -> str: ...
    def candidatos(self, html: str) -> list[Candidato]: ...
    def captura_de_ficha(self, html: str, url: str) -> Captura | None: ...

    # Lo común, que ninguna tienda reescribe
    def obtener(self, referencias: list[Referencia]) -> list[Captura]: ...
    def buscar(self, termino: str, limite: int) -> list[Captura]: ...
```

`buscar` resuelve así: pide la página de búsqueda, saca los candidatos, deduplica por URL, corta
por `limite`, y para cada uno devuelve su `captura` si la trae o pide la ficha si no. Paris mantiene
exactamente su comportamiento actual (una petición más una por resultado); Falabella gasta una.

La base **no es abstracta ni obliga a heredar de ella para cumplir `Fuente`**: el protocolo sigue
siendo lo que define una fuente, y una tienda que no encaje en este molde puede implementarlo por
su cuenta. La base es una comodidad, no una jerarquía.

### Lo que el normalizador genérico gana, y lo que no

Dos cosas suben a `nucleo/normalizador.py` porque son de schema.org, no de Falabella:

- **Desescapar solo cuando hace falta.** `json.loads` primero; si falla, reintentar con
  `html.unescape`. Así un bloque bien formado no se toca —desescapar a ciegas alteraría un nombre
  de producto que contenga `&amp;`— y uno escapado se recupera.
- **Entender `ItemList`.** Un ayudante `productos_ld_json(html) -> list[dict]` que devuelve tanto
  los `Product` de primer nivel como los de `itemListElement[].item`. Es vocabulario de schema.org
  y lo usarán otras tiendas.

Lo que **no** sube: sacar el SKU de la URL, el anclaje al `sellerSkuId`, y el mapeo de las ofertas
sin etiquetar. Eso es de Falabella y vive en su clase.

### La deuda de la tarjeta

`registrar_si_cambio` compara hoy `(precio_internet, precio_normal, precio_tarjeta, disponible)`.
Pasa a comparar también `tarjeta`: si la tienda cambia de tarjeta asociada manteniendo el precio,
hoy no se anota fila y el histórico miente por omisión. Era latente porque Paris no publica
ninguno de los dos campos; con Falabella deja de serlo.

Y `permitir_precio_tarjeta`, que existe en `Reglas` desde la Etapa 1 y hasta ahora no hacía nada
porque ninguna captura traía precio de tarjeta, por fin significa algo.

**No hace falta migración.** `historico_precios` ya tiene `precio_tarjeta` y `tarjeta_asociada`
desde el primer esquema.

## Arquitectura

```
src/fuentes/
├── base.py            # + Candidato, + Captura.precios_etiquetados
├── jsonld.py          # NUEVO: FuenteJsonLd, el andamiaje común
├── paris.py           # adelgaza a sus tres ganchos
├── falabella.py       # NUEVO
└── transporte.py      # sin cambios
src/nucleo/
├── normalizador.py    # + productos_ld_json, desescapado condicional
└── …                  # sin más cambios
runner.py              # + confirmación de capturas inferidas
```

## Flujo de una búsqueda en Falabella

1. Una petición a `falabella.com/falabella-cl/search?Ntt=<término>`.
2. Del único bloque JSON-LD sale un `ItemList` con hasta 56 productos.
3. Cada uno da un `Candidato` con su captura: SKU de la URL, precios inferidos del orden
   ascendente (tres ofertas → tarjeta, internet, normal; dos → internet, normal),
   `precios_etiquetados = False`. La base deduplica y **corta por `limite` aquí**, antes de que
   nada cueste una segunda petición.
4. El orquestador evalúa las reglas contra ese dato. Los que no cumplen se descartan sin escribir.
5. Los que cumplen se confirman: una petición a su ficha, anclando la lista `prices` al
   `sellerSkuId` del producto, y de ahí salen los tres precios etiquetados.
6. Lo demás es idéntico a la Etapa 1.

## Errores

- Falabella responde hoy a un cliente HTTP honesto, pero está tras Akamai y Cloudflare. Si algún
  día bloquea, **bloquea**: se registra y el ciclo sigue con las demás tiendas. No se evade.
- Una ficha cuyo bloque de precios no se pueda anclar al SKU correcto devuelve `None`, como
  cualquier otra captura sin datos utilizables. Mejor ninguna captura que la del producto de al
  lado.
- Un `ItemList` ilegible deja la búsqueda en cero y se registra. No es un error del ciclo.

## Pruebas

`pytest`, **ninguna prueba toca la red**, y las *fixtures* son recortes: la búsqueda real pesa
2,3 MB y la ficha 1,2 MB.

Cobertura mínima para dar la etapa por cerrada:

- **Normalizador**: un bloque escapado con entidades se recupera; uno bien formado **no** se
  altera (un nombre con `&amp;` sobrevive); `productos_ld_json` encuentra los productos de un
  `ItemList` y los de primer nivel.
- **Fuente base**: el deduplicado y el corte por `limite` siguen funcionando; un candidato con
  captura no provoca petición de ficha; uno sin captura sí.
- **Paris**: sus pruebas actuales siguen pasando sin cambios. Es la prueba de que la base no
  rompió nada.
- **Falabella**: SKU sacado de la URL; mapeo de tres ofertas y de dos; `precios_etiquetados` en
  `False` en la búsqueda y en `True` en la ficha; **y el anclaje al `sellerSkuId` con una fixture
  que contenga dos bloques `prices`, uno de promoción y el real** — esta es la prueba que importa.
- **Histórico**: cambiar solo `tarjeta` manteniendo el precio **sí** anota fila.
- **Orquestador**: una captura inferida que no cumple no escribe nada; una que cumple provoca
  exactamente una petición de confirmación y alerta con el precio etiquetado; si la confirmación
  falla, no se alerta ni se escribe.

Cada prueba nueva se comprueba rompiendo a propósito lo que dice medir, antes de darla por buena.

## Criterios de éxito

1. `pytest` pasa entero, sin conexión.
2. Una búsqueda real en Falabella devuelve productos con SKU y precios plausibles, gastando
   **una** petición más una por cada candidato que cumple regla.
3. Una alerta originada en una búsqueda de Falabella lleva un precio **etiquetado**, no inferido.
4. `herramientas/sonda_paris.py` sigue en verde: la base no rompió la tienda que ya funcionaba.
5. `tests/test_capas.py` sigue en verde.

## Riesgos conocidos

**1. La discrepancia sin resolver.** Descrita arriba. Es la primera tarea del plan y condiciona
el resto: si el anclaje al SKU está mal, está mal en el corazón del adaptador.

**2. Falabella puede bloquear.** Hoy no lo hace. Si empieza, la decisión de no evadir significa
perder la tienda, no sortear la defensa. Está asumido desde la Etapa 1.

**3. La base puede no generalizar.** Se diseña con dos tiendas a la vista y una sondada. Si abc.cl
no encaja en los tres ganchos, la base se revisa entonces — con dos implementaciones, que sigue
siendo más barato que con cuatro.

## Siguiente paso

Plan de implementación, con la verificación de la discrepancia como primera tarea.
