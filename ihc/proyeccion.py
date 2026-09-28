"""
ihc.proyeccion - De coordenadas geograficas a pixeles del lienzo.

El mapa se dibuja sobre una lamina de 1800x913 px. Este modulo decide donde
cae cada grado de latitud y longitud dentro de ella, y sobre eso aplica el zoom
y el desplazamiento de la vista:

  1. `Proyeccion`: la familia cartografica (equirectangular o Mercator web) con
     sus limites, que convierte lat/lon en pixeles de la lamina. La lamina es la
     que fue `imagen.png`, una ilustracion de fondo que ya no se dibuja: ahora el
     mapa son los contornos de Natural Earth, pero la proyeccion se sigue
     declarando sobre 1800x913 para que los limites de longitud y los tonos de
     los colores no cambien.
  2. `Calibracion`: un ajuste afin por minimos cuadrados sobre puntos de control
     (GCP). Sirvio para auditar de donde salio la proyeccion comparando la
     ilustracion con los paises; el simulador no lo usa.

Encima se aplica `TransformacionVista` (escala + desplazamiento), que es la que
permite hacer zoom y desplazar el mapa sin tocar la proyeccion.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

Punto = tuple[float, float]


@dataclass(frozen=True)
class Limites:
    """Recorte de la proyeccion en grados."""

    lon_izq: float
    lon_der: float
    lat_sup: float
    lat_inf: float

    @property
    def ancho(self) -> float:
        return self.lon_der - self.lon_izq

    @property
    def alto(self) -> float:
        return self.lat_sup - self.lat_inf


class Proyeccion:
    """Proyeccion equirectangular (base). Se pueden derivar variantes."""

    nombre = "equirectangular"

    def __init__(self, limites: Limites, ancho_px: float, alto_px: float) -> None:
        self.limites = limites
        self.ancho_px = float(ancho_px)
        self.alto_px = float(alto_px)

    # --- proyeccion -----------------------------------------------------
    def _fraccion_y(self, lat: float) -> float:
        return (self.limites.lat_sup - lat) / self.limites.alto

    def a_pixeles(self, lat: float, lon: float) -> Punto:
        """Grados -> pixeles de la imagen del mapa."""
        fraccion_x = ((lon - self.limites.lon_izq) % 360.0) / self.limites.ancho
        return (fraccion_x * self.ancho_px, self._fraccion_y(lat) * self.alto_px)

    def a_grados(self, x: float, y: float) -> Punto:
        """Pxeles de la imagen -> grados (operacion inversa)."""
        lon = self.limites.lon_izq + (x / self.ancho_px) * self.limites.ancho
        lat = self.limites.lat_sup - (y / self.alto_px) * self.limites.alto
        return (lat, ((lon + 180.0) % 360.0) - 180.0)

    def a_grados_limitados(self, x: float, y: float) -> Punto | None:
        """Como `a_grados`, pero devuelve None si el punto cae fuera del mapa."""
        lat, lon = self.a_grados(x, y)
        if not (self.limites.lat_inf <= lat <= self.limites.lat_sup):
            return None
        ancho_grados = self.limites.ancho
        dentro = (lon - self.limites.lon_izq) % 360.0 <= ancho_grados + 1e-9
        return (lat, lon) if dentro else None


class ProyeccionMercator(Proyeccion):
    """Mercator web: mas fiel en latitudes medias, deforma mucho los polos."""

    nombre = "web-mercator"

    def _fraccion_y(self, lat: float) -> float:
        lat = max(-85.05112878, min(85.05112878, lat))
        mercator = math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
        return 0.5 - mercator / (2.0 * math.pi)

    def a_grados(self, x: float, y: float) -> Punto:
        lon = self.limites.lon_izq + (x / self.ancho_px) * self.limites.ancho
        mercator = (0.5 - y / self.alto_px) * 2.0 * math.pi
        lat = math.degrees(2.0 * math.atan(math.exp(mercator)) - math.pi / 2.0)
        return (lat, ((lon + 180.0) % 360.0) - 180.0)


# --------------------------------------------------------------------------
# Ajuste afin por minimos cuadrados (calibracion con puntos de control)
# --------------------------------------------------------------------------

def _resolver_3x3(matriz: list[list[float]], vector: list[float]) -> list[float]:
    """Resuelve un sistema 3x3 por eliminacion de Gauss con pivoteo parcial."""
    m = [fila[:] + [vector[i]] for i, fila in enumerate(matriz)]
    for columna in range(3):
        pivote = max(range(columna, 3), key=lambda f: abs(m[f][columna]))
        if abs(m[pivote][columna]) < 1e-12:
            raise ValueError("matriz singular: los puntos de control estan alineados")
        m[columna], m[pivote] = m[pivote], m[columna]
        for fila in range(3):
            if fila == columna:
                continue
            factor = m[fila][columna] / m[columna][columna]
            for k in range(columna, 4):
                m[fila][k] -= factor * m[columna][k]
    return [m[i][3] / m[i][i] for i in range(3)]


@dataclass(frozen=True)
class GCP:
    """Punto de control: una coordenada real y su pixel en el mapa base."""

    lat: float
    lon: float
    x: float
    y: float
    etiqueta: str = ""


@dataclass(frozen=True)
class Calibracion:
    """Transformacion afin (lon, lat) -> (x, y) obtenida por minimos cuadrados.

    y = a1*lon + a2*lat + a3
    x = b1*lon + b2*lat + b3
    """

    a: tuple[float, float, float]
    b: tuple[float, float, float]
    rms: float
    n_gcp: int

    @classmethod
    def desde_gcp(cls, puntos: Sequence[GCP]) -> "Calibracion":
        if len(puntos) < 3:
            raise ValueError("se necesitan al menos 3 puntos de control")
        n = len(puntos)
        # Ecuaciones normales de minimos cuadrados para cada eje.
        s_lon = sum(p.lon for p in puntos)
        s_lat = sum(p.lat for p in puntos)
        s_ll = sum(p.lon * p.lon for p in puntos)
        s_la = sum(p.lat * p.lat for p in puntos)
        s_cross = sum(p.lon * p.lat for p in puntos)
        matriz = [[s_ll, s_cross, s_lon], [s_cross, s_la, s_lat], [s_lon, s_lat, float(n)]]
        a = _resolver_3x3(matriz, [sum(p.lon * p.y for p in puntos),
                                    sum(p.lat * p.y for p in puntos),
                                    sum(p.y for p in puntos)])
        b = _resolver_3x3(matriz, [sum(p.lon * p.x for p in puntos),
                                    sum(p.lat * p.x for p in puntos),
                                    sum(p.x for p in puntos)])
        residuos = [
            math.hypot(
                (a[0] * p.lon + a[1] * p.lat + a[2]) - p.y,
                (b[0] * p.lon + b[1] * p.lat + b[2]) - p.x,
            )
            for p in puntos
        ]
        rms = math.sqrt(sum(r * r for r in residuos) / n)
        return cls(a=tuple(a), b=tuple(b), rms=rms, n_gcp=n)  # type: ignore[arg-type]

    def a_pixeles(self, lat: float, lon: float) -> Punto:
        return (
            self.b[0] * lon + self.b[1] * lat + self.b[2],
            self.a[0] * lon + self.a[1] * lat + self.a[2],
        )

    def residuo(self, gcp: GCP) -> float:
        x, y = self.a_pixeles(gcp.lat, gcp.lon)
        return math.hypot(x - gcp.x, y - gcp.y)

    def guardar(self, ruta: Path) -> None:
        ruta.write_text(
            json.dumps(
                {
                    "a": list(self.a),
                    "b": list(self.b),
                    "rms_px": round(self.rms, 3),
                    "n_gcp": self.n_gcp,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def cargar(cls, ruta: Path) -> "Calibracion | None":
        if not ruta.exists():
            return None
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return cls(
            a=tuple(datos["a"]),
            b=tuple(datos["b"]),
            rms=float(datos.get("rms_px", 0.0)),
            n_gcp=int(datos.get("n_gcp", 0)),
        )


# --------------------------------------------------------------------------
# Vista: escala y desplazamiento sobre el mapa (base para zoom/pan)
# --------------------------------------------------------------------------

@dataclass
class TransformacionVista:
    """Matriz 2D de la vista: pantalla = escala * mapa + desplazamiento."""

    escala: float = 1.0
    dx: float = 0.0
    dy: float = 0.0

    def aplicar(self, punto_mapa: Punto) -> Punto:
        return (punto_mapa[0] * self.escala + self.dx, punto_mapa[1] * self.escala + self.dy)

    def aplicar_todos(self, puntos: Sequence[Punto]) -> list[Punto]:
        e, dx, dy = self.escala, self.dx, self.dy
        return [(x * e + dx, y * e + dy) for x, y in puntos]

    def invertir(self, punto_pantalla: Punto) -> Punto:
        return ((punto_pantalla[0] - self.dx) / self.escala,
                (punto_pantalla[1] - self.dy) / self.escala)

    def desplazar(self, delta_x: float, delta_y: float) -> None:
        self.dx += delta_x
        self.dy += delta_y

    def encuadrar(self, caja: tuple[float, float, float, float],
                  ancho_disponible: float, alto_disponible: float,
                  escala_maxima: float = 6.0,
                  margen: float = 0.08) -> float:
        """Ajusta escala y desplazamiento para encuadrar una caja del mapa.

        Es el sustituto del zoom manual: en lugar de que el usuario gire la
        rueda, la vista se recalcula sola a partir de los puntos que importan
        (el origen y el destino de la ruta). `escala_maxima` acota el
        acercamiento para que dos airports muy cercanos no produzcan un mapa
        de 0,2 grados de ancho, y la escala nunca baja de 1: mas alla de 1 la
        tierra se veria mas pequena que el mundo real.

        `margen` es la fraction del lienzo que se deja libre alrededor de la
        caja, en cada lado. Sin el, los dos airports quedan pegados al borde:
        en Quito-Madrid el destino caia a 8 px del borde superior y su
        etiqueta se salia de la ventana.
        """
        x0, y0, x1, y1 = caja
        ancho_caja = max(x1 - x0, 1e-6)
        alto_caja = max(y1 - y0, 1e-6)
        # El margen se descuenta del espacio util antes de calcular la escala,
        # para que la caja siga cabiendo con el margen ya aplicado.
        util_x = max(ancho_disponible * (1.0 - 2.0 * margen), 1.0)
        util_y = max(alto_disponible * (1.0 - 2.0 * margen), 1.0)
        escala = min(util_x / ancho_caja, util_y / alto_caja)
        self.escala = max(1.0, min(escala_maxima, escala))
        # Centrar la caja: el punto medio debe caer en el centro del lienzo.
        self.dx = ancho_disponible / 2.0 - (x0 + x1) / 2.0 * self.escala
        self.dy = alto_disponible / 2.0 - (y0 + y1) / 2.0 * self.escala
        return self.escala


class Mapa:
    """La cadena completa: geografia -> pixeles de imagen -> pixeles de pantalla.

    Tambien resuelve el ajuste de la imagen al lienzo conservando la relacion
    de aspecto (`encajar`), que es lo que hacia que la muestra deforma el mapa.
    """

    def __init__(
        self,
        proyeccion: Proyeccion,
        tamano_imagen: tuple[int, int],
        calibracion: Calibracion | None = None,
    ) -> None:
        self.proyeccion = proyeccion
        self.ancho_imagen, self.alto_imagen = tamano_imagen
        self.calibracion = calibracion
        self.vista = TransformacionVista()
        # Rectangulo donde se dibuja la imagen dentro del lienzo.
        self.rect_mapa: tuple[float, float, float, float] = (
            0.0, 0.0, float(self.ancho_imagen), float(self.alto_imagen)
        )
        self.ancho_lienzo = float(self.ancho_imagen)
        self.alto_lienzo = float(self.alto_imagen)

    # --- imagen de referencia -> lienzo --------------------------------
    def encajar(self, ancho_lienzo: int, alto_lienzo: int, margen: int = 0) -> tuple[float, float, float, float]:
        """Escala la imagen para caber en el lienzo sin deformarla.

        Devuelve (x, y, ancho, alto) del area ocupada. Corige el defecto de la
        version de muestra, que redimensionaba a 1000x507 y estiraba el mapa.
        """
        escala = min(
            (ancho_lienzo - 2 * margen) / self.ancho_imagen,
            (alto_lienzo - 2 * margen) / self.alto_imagen,
        )
        ancho = self.ancho_imagen * escala
        alto = self.alto_imagen * escala
        x = (ancho_lienzo - ancho) / 2.0
        y = (alto_lienzo - alto) / 2.0
        self.rect_mapa = (x, y, ancho, alto)
        self.ancho_lienzo = float(ancho_lienzo)
        self.alto_lienzo = float(alto_lienzo)
        # La vista trabaja en pixeles de imagen; el rect se aplica al dibujar.
        return self.rect_mapa

    @property
    def escala_imagen(self) -> float:
        return self.rect_mapa[2] / self.ancho_imagen

    def mapa_a_pantalla(self, punto_mapa: Punto) -> Punto:
        x, y = self.vista.aplicar(punto_mapa)
        return (x * self.escala_imagen + self.rect_mapa[0], y * self.escala_imagen + self.rect_mapa[1])

    def coeficientes_pantalla(self) -> tuple[float, float, float, float]:
        """(kx, ky, cx, cy) de tal modo que pantalla = (x * kx + cx, y * ky + cy).

        Es la misma matriz que `mapa_a_pantalla`, pero escrita en forma abierta
        para el bucle caliente del dibujado: hay 17.000 vertices de contornos y
        `mapa_a_pantalla` dos veces por cada uno en cada fotograma, y con los
        coeficientes por delante la cuenta es una multiplicacion y una suma.
        """
        factor = self.escala_imagen
        escala = self.vista.escala
        return (escala * factor, escala * factor,
                self.vista.dx * factor + self.rect_mapa[0],
                self.vista.dy * factor + self.rect_mapa[1])

    def pantalla_a_mapa(self, punto_pantalla: Punto) -> Punto:
        x0, y0, _, _ = self.rect_mapa
        return self.vista.invertir(((punto_pantalla[0] - x0) / self.escala_imagen,
                                    (punto_pantalla[1] - y0) / self.escala_imagen))

    # --- geografia -> pantalla -----------------------------------------
    def geo_a_mapa(self, lat: float, lon: float) -> Punto:
        if self.calibracion is not None:
            return self.calibracion.a_pixeles(lat, lon)
        return self.proyeccion.a_pixeles(lat, lon)

    def a_pantalla(self, lat: float, lon: float, repetir: bool = False) -> Punto:
        px, py = self.geo_a_mapa(lat, lon)
        if repetir:
            px = self.copia_mas_cercana(px)
        return self.mapa_a_pantalla((px, py))

    def anillo_a_mapa(self, anillo: Sequence[Sequence[float]]) -> list[Punto]:
        """Anillo de GeoJSON, en pixeles del mapa.

        GeoJSON escribe cada coordenada como (longitud, latitud) y `geo_a_mapa`
        espera (latitud, longitud). Aqui se hace el intercambio, que es el punto
        donde se puede equivocar uno: al pasarlo tal cual, cada pais se dibujaba
        girado 90 grados, Japon y Australia se salian del mapa por arriba y
        Ecuador aparecia en el Atlantico, lejos de sus propios aeropuertos.
        """
        return [self.geo_a_mapa(coord[1], coord[0]) for coord in anillo]

    def a_pantalla_todos(self, puntos: Sequence[Sequence[float]]) -> list[Punto]:
        return [self.a_pantalla(p[0], p[1]) for p in puntos]

    def copia_mas_cercana(self, x_mapa: float) -> float:
        """Elige la copia del mundo que queda mas cerca del centro de la vista.

        Al repetir el mapa, un punto geografico tiene una abscisa por cada
        vuelta a la tierra. Dibujar siempre la de 0 a 1.800 pixeles deja
        fuera de la vista lo que esta al otro lado del corte cuando el mapa
        esta desplazado, asi que se selecciona la copia mas cercana.
        """
        if self.vista.escala <= 0:
            return x_mapa
        ancho = self.ancho_mundo
        # `centro` y `x_mapa` estan ambos en pixeles de mapa, asi que el salto
        # se mide en vueltas del mundo, no en vueltas ya escaladas.
        centro = ((self.ancho_lienzo / 2.0 - self.rect_mapa[0]) / self.escala_imagen
                  - self.vista.dx) / self.vista.escala
        return x_mapa + round((centro - x_mapa) / ancho) * ancho

    def rango_x_visible(self) -> tuple[float, float]:
        """Intervalo del mapa, en pixeles de imagen, que ocupa el lienzo."""
        x_izq = self.pantalla_a_mapa((0.0, 0.0))[0]
        x_der = self.pantalla_a_mapa((self.ancho_lienzo, 0.0))[0]
        return (min(x_izq, x_der) - 1.0, max(x_izq, x_der) + 1.0)

    def rango_y_visible(self) -> tuple[float, float]:
        """Igual que `rango_x_visible`, en la vertical."""
        y_sup = self.pantalla_a_mapa((0.0, 0.0))[1]
        y_inf = self.pantalla_a_mapa((0.0, self.alto_lienzo))[1]
        return (min(y_sup, y_inf) - 1.0, max(y_sup, y_inf) + 1.0)

    def repeticiones_activas(self) -> bool:
        """Solo hace falta repetir el mundo cuando la vista esta acercada.

        Sin acercar, la ventana del lienzo suele ser mas ancha que el mundo
        (en un monitor de 1366 px son 2.886 px de mapa frente a 1.800), y pintar
        una segunda copia del planeta solo llenaba los bordes de oceano al
        doble del coste: los 177 paises pasaban de 161 a 354 elementos y el
        redibujo de 30 a 98 ms. Al acercar, la ventana es mas estrecha que el
        mundo y la repeticion si es imprescindible, porque el corte del Atlantico
        cae en mitad de la vista.
        """
        return self.vista.escala > 1.0

    def copias_de_x(self, x_min: float, x_max: float) -> list[float]:
        """Vueltas del mundo en las que el tramo [x_min, x_max] se ve de verdad.

        Cada pais tiene que repetirse en todas las copias del mundo que tocan
        el lienzo. Sin esto, al desplazar la vista hacia la copia central se
        veia oceano sin costa: el mapa dejaba de ser coherente.

        El filtro importa por rendimiento. Una cuenta puramente matematica da
        cuatro vueltas candidatas para un pais ancho; devolverlas todas
        dibujaba los 177 paises dos veces (354 elementos y 98 ms) cuando solo
        una copia era visible. Aqui se descartan las que no intersecan.
        """
        ancho = self.ancho_mundo
        if ancho <= 0:
            return [0.0]
        visible_izq, visible_der = self.rango_x_visible()
        if not self.repeticiones_activas():
            centro = (visible_izq + visible_der) / 2.0
            k = math.floor((centro - (x_min + x_max) / 2.0) / ancho + 0.5)
            return [k * ancho]
        k_ini = math.floor((visible_izq - x_max) / ancho)
        k_fin = math.floor((visible_der - x_min) / ancho)
        copias: list[float] = []
        for k in range(k_ini, k_fin + 1):
            vuelta = k * ancho
            if x_min + vuelta <= visible_der and x_max + vuelta >= visible_izq:
                copias.append(vuelta)
        if copias:
            return copias
        # Si el tramo cae en un hueco entre copias, se dibuja en la mas cercana.
        centro = (x_min + x_max) / 2.0
        k = math.floor(((visible_izq + visible_der) / 2.0 - centro) / ancho)
        return [k * ancho]

    def a_grados(self, punto_pantalla: Punto) -> Punto | None:
        """Punto de pantalla -> (lat, lon), o None si cae fuera del mapa."""
        x_mapa, y_mapa = self.pantalla_a_mapa(punto_pantalla)
        if self.calibracion is not None:
            return _invertir_calibracion(self.calibracion, x_mapa, y_mapa)
        return self.proyeccion.a_grados_limitados(x_mapa, y_mapa)

    def dentro_del_mapa(self, punto_pantalla: Punto) -> bool:
        x, y, ancho, alto = self.rect_mapa
        return x <= punto_pantalla[0] <= x + ancho and y <= punto_pantalla[1] <= y + alto

    # --- repeticion del mundo -------------------------------------------
    @property
    def ancho_mundo(self) -> float:
        """Ancho en pixeles de mapa de una vuelta completa a la tierra."""
        return float(self.ancho_imagen)

    def caja_de_ruta(self, puntos: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
        """Caja (x0, y0, x1, y1) en pixeles de mapa que contiene la ruta.

        Al repetir el mundo, los puntos de una ruta que cruza el corte se
        desplazan para quedar en una serie continua, y asi la caja abarca la
        trayectoria real y no el mapa entero.
        """
        if not puntos:
            return (0.0, 0.0, 0.0, 0.0)
        ancho = self.ancho_mundo
        x0, y0, x1, y1 = math.inf, math.inf, -math.inf, -math.inf
        anterior: float | None = None
        for punto in puntos:
            px, py = self.geo_a_mapa(punto[0], punto[1])
            if anterior is not None:
                # Mantener la continuidad al cruzar el corte del mapa.
                while px - anterior > ancho / 2.0:
                    px -= ancho
                while px - anterior < -ancho / 2.0:
                    px += ancho
            anterior = px
            x0, y0 = min(x0, px), min(y0, py)
            x1, y1 = max(x1, px), max(y1, py)
        return (x0, y0, x1, y1)

    def encuadrar_puntos(self, puntos: Sequence[Sequence[float]],
                         escala_maxima: float = 6.0) -> float:
        """Encuadra la ruta entera en el lienzo y devuelve la escala usada."""
        return self.encuadrar_puntos_para_caja(self.caja_de_ruta(puntos), escala_maxima)

    def encuadrar_puntos_para_caja(self, caja: tuple[float, float, float, float],
                                   escala_maxima: float = 6.0) -> float:
        """Igual que `encuadrar_puntos`, pero recibiendo la caja ya calculada."""
        _, _, ancho, alto = self.rect_mapa
        if ancho <= 0 or alto <= 0:
            return 1.0
        factor = self.escala_imagen
        return self.vista.encuadrar(caja, ancho / factor, alto / factor, escala_maxima)


def _invertir_calibracion(cal: Calibracion, x: float, y: float) -> Punto | None:
    """Resuelve el sistema lineal de la calibracion para obtener (lat, lon)."""
    # y = a0*lon + a1*lat + a2 ;  x = b0*lon + b1*lat + b2
    det = cal.a[0] * cal.b[1] - cal.a[1] * cal.b[0]
    if abs(det) < 1e-12:
        return None
    dy = y - cal.a[2]
    dx = x - cal.b[2]
    lon = (dy * cal.b[1] - cal.a[1] * dx) / det
    lat = (cal.a[0] * dx - dy * cal.b[0]) / det
    if not (-90.0 <= lat <= 90.0):
        return None
    return (lat, ((lon + 180.0) % 360.0) - 180.0)
