"""
ihc.cuadricula - Meridianos y paralelos, en el mapa y en la esfera.

Son dos capas que el usuario leeria como la misma y no lo son:

  * `rejilla` dibuja la malla en la proyeccion del mapa. En la equirectangular
    los meridianos y los paralelos salen **rectos**, y esa rectitud es la
    proyeccion: el cilindro se desarrolla sin curvar. Es la referencia real de
    coordenadas, la que permite leer la latitud de un punto mirando la linea
    de al lado.
  * `rejilla_esfera` dibuja los mismos meridianos y paralelos sobre una esfera
    vista de frente (proyeccion ortografica), donde si se curvan. No coincide
    con el mapa porque no es la misma proyeccion, asi que va en un globo aparte,
    rotulado, y no superpuesta al mapa: superponerla haria que las curvas
    parecieran un error de dibujo en vez de la explicacion de la deformacion.

Juntas cuentan la idea entera: el mapa plano es el cilindro desarrollado y el
globo es la esfera. Verlas a la vez es lo que hace entendible por que la
equirectangular deforma las areas en latitudes altas.

Decision de interfaz (no de dibujo): la capa nace apagada y se enciende con un
boton o con la tecla G. Encendida por defecto taparia la costa de la imagen de
fondo y las 22 lineas aparecerian en cada una de las capturas del manual, que
ya estan hechas sin ellas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from . import geo
from .proyeccion import Limites, Mapa, Proyeccion

Punto = tuple[float, float]
Linea = list[Punto]

# Separacion de la rejilla, en grados. 30 para la malla mayor y 15 para las lineas
# finas: por debajo de 15 grados la lamina de 1800 px deja menos de 42 px entre
# meridianos y el mapa se convierte en una trama en la que no se ve la costa.
PASO_LON = 30.0
PASO_LAT = 30.0
PASO_LAT_MENOR = 15.0

# Muestras por linea. En la equirectangular sobrarian dos, porque meridianos y
# paralelos son rectos y bastaria el par de extremos: el recorte es margen de
# sobra para cuando la proyeccion curva. No cuesta nada porque las polilineas
# se guardan en pixeles de mapa y se reutilizan, de modo que el coste por
# fotograma es solo la transformada afin.
MUESTRAS_MERIDIANO = 61
MUESTRAS_PARALELO = 121

# Tamaño del globo, en fraccion del alto del lienzo y limites en pixeles. Por
# debajo de 34 px la malla de la esfera deja de leerse y por encima de 92 tapa
# demasiado mapa; el inset es decorativo, no una vista de trabajo.
RADIO_ESFERA_MIN = 34.0
RADIO_ESFERA_MAX = 92.0
FRACCION_ESFERA_ALTO = 0.19
FRACCION_ESFERA_ANCHO = 0.13
MARGEN_ESFERA = 12.0

# Tamaños minimos de lienzo para colocar el globo. Con el lienzo mas pequeno que
# genera la aplicacion (640x360) siempre cabe, pero la funcion es comprobable
# sin abrir una ventana y hay probarlas en el limite.
ANCHO_MIN_ESFERA = 260
ALTO_MIN_ESFERA = 220


@dataclass(frozen=True)
class LineaRejilla:
    """Un meridiano o un paralelo ya proyectado a pixeles de mapa.

    `clase` decide como se pinta y si lleva etiqueta:

        "ecuator"  el paralelo de 0 grados, mas grueso y con su nombre
        "mayor"    la malla de `PASO_LON` / `PASO_LAT`, con etiqueta en el borde
        "menor"    la malla de 15 grados, sin etiqueta y con trazo discontinuo

    `eje` dice si la linea es un meridiano ("lon") o un paralelo ("lat"), que es
    lo que decide por que borde se le pone la etiqueta. Se guarda en pixeles de
    mapa y no de pantalla porque no depende de la vista: asi se calcula una vez y
    en cada fotograma solo se aplica la matriz `pantalla = x*k + c`.
    """

    puntos: Linea
    clase: str
    grado: float
    eje: str


@dataclass(frozen=True)
class LineaEsfera:
    """Un meridiano o un paralelo sobre la esfera, ya en pixeles de pantalla.

    `clase` es "ecuator", "central" (el meridiano que pasa por el centro de la
    vista) o "mayor". Los tramos de la cara oculta llegan vacios y no se dibujan.
    """

    puntos: Linea
    clase: str
    grado: float


# --------------------------------------------------------------------------
# La rejilla sobre el mapa
# --------------------------------------------------------------------------

def grados_alineados(inf: float, sup: float, paso: float, incluir_borde: bool = False
                     ) -> list[float]:
    """Grados dentro de [inf, sup] que caen en un multiplo de `paso`.

    El borde de la lamina se excluye por defecto: los 90 grados de latitud
    coinciden con el marco del mapa y la linea se dibujaria dos veces, con el
    doble de grosor, justo en el borde.
    """
    primero = math.ceil(inf / paso) * paso
    ultimo = math.floor(sup / paso) * paso
    grados: list[float] = []
    g = primero
    while g <= ultimo + 1e-9:
        if incluir_borde or (g > inf + 1e-9 and g < sup - 1e-9):
            grados.append(round(g, 6))
        g += paso
    return grados


def meridiano(proyeccion: Proyeccion, lon: float, limites: Limites,
              muestras: int = MUESTRAS_MERIDIANO) -> Linea:
    """Meridiano `lon` de polo a polo, en pixeles de mapa.

    Se muestrea en grados y se proyecta punto a punto, en vez de trazar una
    vertical de un extremo a otro: asi la linea sigue a la proyeccion si alguna
    vez se cambia (en Mercator el meridiano sigue recto, pero un punto suelto
    no lo estorba) y las pruebas pueden comprobar que pasa por los grados
    correctos.
    """
    paso = limites.alto / max(muestras - 1, 1)
    return [proyeccion.a_pixeles(min(limites.lat_sup, limites.lat_inf + i * paso), lon)
            for i in range(muestras)]


def paralelo(proyeccion: Proyeccion, lat: float, limites: Limites,
             muestras: int = MUESTRAS_PARALELO) -> Linea:
    """Paralelo `lat` de un borde al otro, en pixeles de mapa.

    El ultimo punto se queda a un paso del borde derecho a proposito. La
    proyeccion envuelve la longitud (`(+330) % 360` cae en 0, que es el mismo
    borde izquierdo), asi que muestrear justo en `lon_der` devolveria el origen
    de la linea y el `create_line` cruzaria el mapa entero de lado a lado, que es
    el mismo defecto que tiene el corte del Atlantico en las rutas.
    """
    paso = limites.ancho / muestras
    return [proyeccion.a_pixeles(lat, limites.lon_izq + i * paso) for i in range(muestras)]


def rejilla(proyeccion: Proyeccion, limites: Limites) -> list[LineaRejilla]:
    """La malla completa del mapa, lista para dibujar y para cachear.

    Se construye una sola vez: depende de la proyeccion, que no cambia durante
    la ejecucion. Devuelve los meridianos primero y despues los paralelos, cada
    uno con su clase y su grado para la etiqueta.
    """
    lineas: list[LineaRejilla] = []
    for lon in grados_alineados(limites.lon_izq, limites.lon_der, PASO_LON):
        lineas.append(LineaRejilla(meridiano(proyeccion, lon, limites), "mayor", lon, "lon"))
    for lat in grados_alineados(limites.lat_inf, limites.lat_sup, PASO_LAT_MENOR):
        clase = "ecuator" if abs(lat) < 1e-9 else (
            "mayor" if abs(lat) % PASO_LAT < 1e-9 else "menor")
        lineas.append(LineaRejilla(paralelo(proyeccion, lat, limites), clase, lat, "lat"))
    return lineas


def etiqueta_lat(lat: float) -> str:
    """Grado de latitud para rotular: 0, 30 N, 30 S."""
    if abs(lat) < 1e-6:
        return "0°"
    return f"{abs(lat):.0f}° {'N' if lat > 0 else 'S'}"


def etiqueta_lon(lon: float) -> str:
    """Grado de longitud para rotular, en el meridiano de Greenwich.

    El mapa va de -30 a +330, de modo que 330 grados son los 30 oeste y no un
    numero mayor que 180. Sin normalizar, el borde derecho del mapa diria
    "330° E" y pareceria un error de la proyeccion. El antimeridiano se rotula
    sin cardinal porque los 180 este y los 180 oeste son la misma linea.
    """
    lon = geo.normalizar_lon(lon)
    if abs(lon) < 1e-6:
        return "0°"
    if abs(abs(lon) - 180.0) < 1e-6:
        return "180°"
    return f"{abs(lon):.0f}° {'E' if lon > 0 else 'O'}"


def texto_etiqueta(linea: LineaRejilla) -> str:
    """Lo que se escribe junto a una linea de la malla."""
    if linea.clase == "ecuator":
        return "Ecuador 0°"
    return etiqueta_lat(linea.grado) if linea.eje == "lat" else etiqueta_lon(linea.grado)


# --------------------------------------------------------------------------
# La misma rejilla sobre la esfera (proyeccion ortografica)
# --------------------------------------------------------------------------

def ortografica(lat: float, lon: float, lat0: float, lon0: float, radio: float,
                centro: Punto) -> Punto | None:
    """Punto de la esfera, en pixeles, visto de frente desde (lat0, lon0).

    Es la proyeccion ortografica: el observador esta en el infinito, en la
    direccion (lat0, lon0), y cada punto de la esfera se proyecta a lo largo de
    la recta que lo une con el observador. Lo que se ve es un circulo, no el
    elipse que deforma la proyeccion de Mercator.

    Devuelve None para lo que queda en la cara oculta: un meridiano o un
    paralelo se dibuja partido, no atravesado, y de ahi que el punto invisible
    sea None y no un pixel en el centro.

    El margen de `cos_c` no es un detalle numerico. El meridiano que cae
    exactamente a 90 grados del centro esta justo en el limbo, y por error de
    redondeo `cos_c` sale en 1e-17 en vez de 0: sin el margen se dibujaria
    entero y por dentro del disco. Con el margen, el limbo se dibuja una sola
    vez, con el circunculo.

    `y` sale invertido porque en la pantalla la y crece hacia abajo y aqui crece
    hacia el norte, como en cualquier carta.
    """
    phi0 = math.radians(lat0)
    lam0 = math.radians(lon0)
    phi = math.radians(lat)
    dlam = math.radians(lon - lon0)
    sin_phi0, cos_phi0 = math.sin(phi0), math.cos(phi0)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    cos_c = sin_phi0 * sin_phi + cos_phi0 * cos_phi * math.cos(dlam)
    if cos_c <= 1e-9:
        return None
    x = cos_phi * math.sin(dlam)
    y = cos_phi0 * sin_phi - sin_phi0 * cos_phi * math.cos(dlam)
    return (centro[0] + radio * x, centro[1] - radio * y)


def _tramos_visibles(muestras: Sequence[Punto | None]) -> list[Linea]:
    """Parte una secuencia con huecos en los tramos de puntos consecutivos.

    Es lo que hace que la malla de la esfera se corte en el limbo en vez de
    cruzar el disco: al otro lado del globo la linea se pierde y vuelve a salir.
    """
    tramos: list[Linea] = []
    actual: Linea = []
    for punto in muestras:
        if punto is None:
            if len(actual) > 1:
                tramos.append(actual)
            actual = []
        else:
            actual.append(punto)
    if len(actual) > 1:
        tramos.append(actual)
    return tramos


def rejilla_esfera(lat0: float, lon0: float, radio: float, centro: Punto,
                   paso: float = PASO_LON, muestras: int = 49
                   ) -> list[LineaEsfera]:
    """Malla de meridianos y paralelos sobre la esfera centrada en (lat0, lon0).

    Difiere de la del mapa en lo unico que importa para la pregunta que quiere
    contestar: aqui los meridianos son arcos y los paralelos son curvas que se
    estrechan hacia los polos. En el mapa, rectos.

    Se muestrean las lineas enteras y se descartan los tramos ocultos, en vez de
    calcular que parte de cada paralelo es visible. El calculo directo obliga a
    partir el paralelo por el antimeridiano del centro, y con la muestreacion se
    resuelve solo y con el mismo codigo para meridianos y paralelos.
    """
    lineas: list[LineaEsfera] = []
    # --- meridianos: de polo a polo, uno por cada multiplo de `paso` -----
    # El recorrido es [0, 360) y no [0, 360]: 0 y 360 son el mismo meridiano y
    # con el borde incluido se dibujaria dos veces, y el central marcado como
    # central, con el dobro de grosor, justo en el medio del disco.
    for lon in grados_alineados(0.0, 360.0 - 1e-6, paso, incluir_borde=True):
        central = abs(((lon - lon0 + 180.0) % 360.0) - 180.0) < 1e-6
        for tramo in _tramos_visibles([
                ortografica(min(90.0, -90.0 + 180.0 * i / (muestras - 1)), lon,
                            lat0, lon0, radio, centro) for i in range(muestras)]):
            lineas.append(LineaEsfera(tramo, "central" if central else "mayor", lon))
    # --- paralelos: de -60 a 60. Los de 90 grados se reducen a un punto --
    for lat in grados_alineados(-60.0, 60.0, paso, incluir_borde=True):
        for tramo in _tramos_visibles([
                ortografica(lat, lon0 - 180.0 + 360.0 * i / (muestras - 1),
                            lat0, lon0, radio, centro) for i in range(muestras)]):
            lineas.append(LineaEsfera(tramo, "ecuator" if abs(lat) < 1e-9 else "mayor", lat))
    return lineas


def colocar_esfera(ancho_lienzo: float, alto_lienzo: float,
                   rect_mapa: Sequence[float] | None = None,
                   margen: float = MARGEN_ESFERA) -> tuple[float, float, float] | None:
    """Sitio del globo en la esquina inferior derecha: (centro_x, centro_y, radio).

    Se ancla al **mapa**, no a la ventana, y por un motivo que se ve al abrir la
    aplicacion: el lienzo es ancho y bajo (1306x369 en un portatil), de modo que
    la lamina de proporcion 1,97 queda centrada y sobran margenes negros a los
    lados. En la esquina de la ventana el globo caeria sobre el negro, a 150 px
    del mapa, y se leeria como un elemento flotante en vez de como una miniatura
    del mapa. Pegado a la esquina de la lamina se lee como lo que es.

    Abajo a la derecha porque la barra de ruta, los paneles y el plano del avion
    manual quedan a la izquierda y arriba, y porque el globo es un adorno: si
    estorba, se apaga con G.

    El rect se recorta a la ventana, porque al acercar el mapa sus bordes se
    salen y el globo se iria con ellos.

    Devuelve None cuando no cabe el disco minimo, lo que pasa con un lienzo
    pequeno o con el mapa casi entero fuera de la pantalla. El lienzo mas
    pequeno que produce la aplicacion son 640x360, de modo que en la practica
    siempre hay sitio.
    """
    x0, y0, ancho, alto = rect_mapa if rect_mapa is not None else (0.0, 0.0,
                                                                 ancho_lienzo, alto_lienzo)
    # Parte visible del mapa, en pixeles de pantalla.
    visible_izq, visible_sup = max(x0, 0.0), max(y0, 0.0)
    visible_der, visible_inf = min(x0 + ancho, ancho_lienzo), min(y0 + alto, alto_lienzo)
    if (visible_der - visible_izq) < ANCHO_MIN_ESFERA or \
            (visible_inf - visible_sup) < ALTO_MIN_ESFERA:
        return None
    radio = min((visible_inf - visible_sup) * FRACCION_ESFERA_ALTO,
                (visible_der - visible_izq) * FRACCION_ESFERA_ANCHO)
    radio = max(RADIO_ESFERA_MIN, min(RADIO_ESFERA_MAX, radio))
    return (visible_der - margen - radio, visible_inf - margen - radio, radio)


def centro_de_vista(mapa: Mapa) -> geo.Punto:
    """Latitud y longitud del punto central del lienzo.

    El globo se centra aqui, de modo que gira con la vista: al desplazar el mapa
    se ve que el trozo que se mira es otra parte de la misma esfera. Si el centro
    cae fuera de la lamina (la vista se ha desplazado mas alla del mapa) se
    devuelve el centro de la proyeccion, que siempre es valido.
    """
    grados = mapa.a_grados((mapa.ancho_lienzo / 2.0, mapa.alto_lienzo / 2.0))
    if grados is not None:
        return geo.Punto(grados[0], grados[1])
    limites = mapa.proyeccion.limites
    return geo.Punto((limites.lat_sup + limites.lat_inf) / 2.0,
                     limites.lon_izq + limites.ancho / 2.0)
