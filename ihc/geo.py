"""
ihc.geo - Geodesia para el simulador.

La version de muestra del profesor media distancias "en pixeles" y las
multiplicaba por una constante arbitraria (0.621). Aqui se trabaja con
coordenadas geograficas reales (latitud/longitud en grados) y formulas
 geodesicas, de modo que las cifras que muestra la interfaz son
verificables: la distancia Quito-Madrid es 8.7 millones de metros, no un
numero inventado por la escala del lienzo.

Formulas usadas (documentadas para el manual):
  * Haversine        : distancia de gran circulo entre dos puntos de la esfera.
  * Rumbo inicial    : angulo norte-sur del arco que une dos puntos.
  * Interpolacion    : punto sobre el arco (interpolacion esferica).
  * math.sqrt        : distancia euclidiana en el plano de la pantalla, que se
                       conserva para medir el desplazamiento del puntero
                       (es el comando de la "Guia de comandos" de la practica).
"""

from __future__ import annotations

import math
from typing import Iterable, NamedTuple, Sequence

# Radio medio terrestre segun el IUGN (promedio de WGS84).
RADIO_TIERRA_KM = 6371.0088
GRADOS_POR_RADIAN = 180.0 / math.pi


class Punto(NamedTuple):
    """Un punto geografico. `lat` en grados, `lon` en grados."""

    lat: float
    lon: float


def normalizar_lon(lon: float) -> float:
    """Lleva una longitud al intervalo [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


def diferencia_lon(lon_a: float, lon_b: float) -> float:
    """Diferencia longitudinal mas corta, útil si la ruta cruza el antimeridiano."""
    return normalizar_lon(lon_b - lon_a)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en kilometros entre dos puntos de la superficie terrestre.

    Es la formula de haversine: a diferencia de la formula de latitud-longitud
    "plana", no pierde precision entre puntos muy cercanos y no diverge para
    separaciones grandes, por lo que sirve tanto para un tramo de 2 km como
    para un vuelo intercontinental.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(diferencia_lon(lon1, lon2))
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * RADIO_TIERRA_KM * math.asin(math.sqrt(min(1.0, a)))


def rumbo_inicial(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Rumbo inicial del arco de gran circulo, en grados (0 = norte, 90 = este)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(diferencia_lon(lon1, lon2))
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def punto_sobre_arco(
    lat1: float, lon1: float, rumbo: float, distancia_km: float
) -> Punto:
    """Punto alcanzado desde (lat1, lon1) siguiendo `rumbo` `distancia_km`."""
    delta = distancia_km / RADIO_TIERRA_KM
    theta = math.radians(rumbo)
    phi1, lambda1 = math.radians(lat1), math.radians(lon1)
    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    sin_phi2 = max(-1.0, min(1.0, sin_phi2))
    phi2 = math.asin(sin_phi2)
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * sin_phi2,
    )
    return Punto(math.degrees(phi2), normalizar_lon(math.degrees(lambda2)))


def interpolar(punto_a: Sequence[float], punto_b: Sequence[float], fraccion: float) -> Punto:
    """Punto a una fraccion (0..1) del arco de gran circulo entre A y B.

    Se usa para animar el vuelo automatico: el avion recorre la ruta geodesica
    real (la que usarian las aerolineas), no una recta en el plano de la
    pantalla.
    """
    lat1, lon1 = punto_a[0], punto_a[1]
    lat2, lon2 = punto_b[0], punto_b[1]
    total = haversine(lat1, lon1, lat2, lon2)
    if total < 1e-9:
        return Punto(lat1, lon1)
    rumbo = rumbo_inicial(lat1, lon1, lat2, lon2)
    return punto_sobre_arco(lat1, lon1, rumbo, total * fraccion)


def longitud_ruta(puntos: Iterable[Sequence[float]]) -> float:
    """Distancia total en km de una polilinea de puntos geograficos."""
    total = 0.0
    anterior: Sequence[float] | None = None
    for punto in puntos:
        if anterior is not None:
            total += haversine(anterior[0], anterior[1], punto[0], punto[1])
        anterior = punto
    return total


def distancia_euclidiana(x1: float, y1: float, x2: float, y2: float) -> float:
    """Distancia en pixeles entre dos puntos de la pantalla (math.sqrt).

    Se conserva a proposito: es el comando `math.sqrt` exigido por la Guia de
    comandos de la practica y es la medida correcta para el puntero, que se
    mueve en el plano del lienzo y no sobre la esfera.
    """
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def km_a_millas(kilometros: float) -> float:
    return kilometros * 0.621371


def formatear_distancia(kilometros: float) -> str:
    """Presentacion adaptativa: metros cortos, kilometros medios, miles de km largos."""
    if kilometros < 1.0:
        return f"{kilometros * 1000.0:,.0f} m"
    if kilometros < 100.0:
        return f"{kilometros:,.1f} km"
    return f"{kilometros:,.0f} km"
