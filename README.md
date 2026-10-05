# Rastreador de ofertas — retail chileno

Vigila precios de tiendas chilenas, guarda el histórico de variaciones y avisa
cuando algo baja de verdad.

## Puesta en marcha

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edita `config/lista_deseos.yaml` con lo que quieras vigilar y ejecuta:

```
python runner.py
```

## Pruebas

```
python -m pytest
```

No tocan la red. Para comprobar contra Paris de verdad:

```
python herramientas/sonda_paris.py notebook
```

## Cómo está hecho

Cada tienda es una `Fuente` que devuelve `Captura`. El núcleo no sabe de HTTP ni
de qué tienda viene el dato, así que añadir una tienda nueva no toca el núcleo.

El histórico guarda **variaciones**, no pasadas: una fila solo cuando el precio o
el stock cambian.

No se evade la detección de robots. Si una tienda bloquea, queda registrada y el
ciclo sigue con las demás.

El diseño está en `docs/specs/` y el plan en `docs/plans/`.
