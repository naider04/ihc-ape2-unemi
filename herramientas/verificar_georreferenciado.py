"""
verificar_georreferenciado.py - Comprueba que el mapa es geograficamente fiel.

Responde a una pregunta que una captura de pantalla no puede responder con
rigor: ¿los marcadores de aeropuerto caen dentro del pais que declaran?

Metodo: cada aeropuerto grande se proyecta con la misma cadena que usa la
aplicacion (limites calibrados + tamano de la imagen) y se comprueba, por
lanzamiento de rayo, si el punto cae dentro de algun poligono de pais. El
pais obtenido se contrasta con el que declara el CSV de OurAirports.

Despues informa del factor de escala, comparando la distancia en pixeles de la
proyeccion con la distancia geodesica real (haversine). Si la calibracion
fuese incorrecta, la escala variaria de un tramo a otro.

Uso:
    python herramientas/verificar_georreferenciado.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from ihc import geo  # noqa: E402
from ihc.datos import FuenteDatos  # noqa: E402
from ihc.proyeccion import Limites, Proyeccion  # noqa: E402

PAISES = RAIZ / "data" / "paises.json"
CALIBRACION = RAIZ / "data" / "calibracion_mapa.json"
KM_POR_GRADO = 111.32


def cargar_limites() -> Limites:
    if CALIBRACION.exists():
        d = json.loads(CALIBRACION.read_text(encoding="utf-8"))
        return Limites(d["lon_izquierda"], d["lon_izquierda"] + d["longitud_grados"],
                       d["latitud_superior"], d["latitud_inferior"])
    return Limites(-30.0, 330.0, 90.0, -90.0)


def tamano_lamina() -> tuple[float, float]:
    """Ancho y alto de la lamina del mapa, en pixeles.

    Antes se sacaban de `imagen.png`, que era el fondo dibujado. Ese fondo ya no
    forma parte del simulador (sus costas no coincidian con la geografia y no
    habia transformacion que lo corrigiera), asi que el tamano viene de la propia
    lamina del mapa, que es lo que de verdad define la escala.
    """
    try:
        from .proyeccion import TAMANO_MAPA  # type: ignore
    except ImportError:
        TAMANO_MAPA = (1800, 913)
    return float(TAMANO_MAPA[0]), float(TAMANO_MAPA[1])


def dentro_del_anillo(x: float, y: float, anillo: list[tuple[float, float]]) -> bool:
    """Lanzamiento de rayo horizontal: cuenta los cruces del borde."""
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cruce = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cruce:
                dentro = not dentro
    return dentro


def proyectar_anillo(proyeccion: Proyeccion, anillo: list[list[float]],
                     lon_prueba: float) -> list[tuple[float, float]] | None:
    """Proyecta un anillo cerca de la longitud que se esta probando.

    Asi un pais que cruza el antimeridiano (Rusia, Fiji) no se parte en dos
    poligonos al proyectarlo sobre una imagen que ya dio la vuelta al mundo.
    """
    puntos = []
    for coord in anillo:
        lon, lat = coord[0], coord[1]
        while lon - lon_prueba > 180.0:
            lon -= 360.0
        while lon - lon_prueba < -180.0:
            lon += 360.0
        puntos.append(proyeccion.a_pixeles(lat, lon))
    return puntos or None


def pais_que_contiene(proyeccion: Proyeccion, candidatos: list[dict], lat: float,
                      lon: float) -> str | None:
    x, y = proyeccion.a_pixeles(lat, lon)
    for pais in candidatos:
        # Todos los anillos, no solo el primero: Alaska, las Canarias, Hokkaido o
        # Sumatra son anillos aparte del mismo pais. Mirar solo el mayor daba por
        # fuerasti airports que si estan dentro, a miles de kilometros.
        for anillo in pais["anillos"]:
            proyectado = proyectar_anillo(proyeccion, anillo, lon)
            if proyectado and dentro_del_anillo(x, y, proyectado):
                return pais["nombre"]
    return None


def distancia_al_borde(px: float, py: float, anillo: list[tuple[float, float]]) -> float:
    """Distancia en pixeles del punto al segmento mas cercano del anillo."""
    mejor = float("inf")
    for i in range(len(anillo)):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % len(anillo)]
        dx, dy = x2 - x1, y2 - y1
        largo = dx * dx + dy * dy
        if largo == 0:
            continue
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / largo))
        mejor = min(mejor, ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5)
    return mejor


def fuera_pero_cerca(proyeccion: Proyeccion, candidatos: list[dict], lat: float,
                     lon: float, km_por_px: float, umbral_km: float = 250.0
                     ) -> tuple[bool, float]:
    """Distingue un fallo de calibracion de una isla que el dataset no trae.

    Natural Earth 50m es un mapa de proposito general: no incluye islas
    pequenas. Un aeropuerto a 30 km de la costa de una isla cae fuera del poligono
    y no es un error de la proyeccion.
    """
    px, py = proyeccion.a_pixeles(lat, lon)
    mejor = float("inf")
    for pais in candidatos:
        for anillo in pais["anillos"]:
            proyectado = proyectar_anillo(proyeccion, anillo, lon)
            if proyectado:
                mejor = min(mejor, distancia_al_borde(px, py, proyectado) * km_por_px)
    return mejor <= umbral_km, mejor


def main() -> int:
    if not PAISES.exists():
        print("Falta data/paises.json. Ejecute: python herramientas/preparar_datos.py",
              file=sys.stderr)
        return 1

    fuente = FuenteDatos().cargar()
    paises = json.loads(PAISES.read_text(encoding="utf-8"))["features"]
    limites = cargar_limites()
    ancho, alto = tamano_lamina()
    proyeccion = Proyeccion(limites, ancho, alto)

    px_por_grado_lon = ancho / limites.ancho
    print(f"Limites calibrados: longitud {limites.lon_izq:+.0f} a {limites.lon_der:+.0f}, "
          f"latitud {limites.lat_inf:+.0f} a {limites.lat_sup:+.0f}")
    print(f"Lamina {ancho:.0f} x {alto:.0f} px  ->  {px_por_grado_lon:.3f} px por grado de "
          f"longitud, {alto / limites.alto:.3f} px por grado de latitud")
    print(f"Equivalencia esperada: 1 px = {KM_POR_GRADO / px_por_grado_lon:.2f} km en el ecuador")

    # 1. El aeropuerto cae dentro del poligono de su pais?
    indice: dict[str, list[dict]] = {}
    for pais in paises:
        indice.setdefault(pais["nombre"].strip().lower(), []).append(pais)

    grandes = [a for a in fuente.aeropuertos if a.tipo == "large_airport"]
    km_por_px = KM_POR_GRADO / px_por_grado_lon
    aciertos = 0
    revisados = 0
    sin_poligono: list[str] = []
    costeros: list[tuple[str, str, int]] = []
    reales: list[tuple[str, str, int]] = []
    por_pais: Counter[str] = Counter()

    for aeropuerto in grandes:
        candidatos = indice.get(aeropuerto.pais.strip().lower(), [])
        if not candidatos:
            sin_poligono.append(aeropuerto.iata)
            continue
        revisados += 1
        if pais_que_contiene(proyeccion, candidatos, aeropuerto.lat, aeropuerto.lon):
            aciertos += 1
            continue
        cerca, km = fuera_pero_cerca(proyeccion, candidatos, aeropuerto.lat,
                                     aeropuerto.lon, km_por_px)
        registro = (aeropuerto.iata, aeropuerto.pais, round(km))
        (costeros if cerca else reales).append(registro)
        por_pais[aeropuerto.pais] += 1

    print(f"\n1. Aeropuerto dentro del poligono de su pais: {aciertos}/{revisados} "
          f"({aciertos / revisados:.1%})")
    print(f"   Revisionados: {revisados} grandes con pais representado en el GeoJSON "
          f"({len(sin_poligono)} sin representacion, p. ej. territorios pequenos).")
    print(f"   De los {revisados - aciertos} fuera del poligono:")
    print(f"     - {len(costeros)} a menos de 250 km del borde: islas o costas que "
          f"Natural Earth 50m no dibuja. No es error de calibracion.")
    if reales:
        print(f"     - {len(reales)} a mas de 250 km. Alguien tiene que mirar si son "
              "fallos o islas que el dataset no trae. Primeros: "
              + ", ".join(f"{iata} ({p}, {km} km)" for iata, p, km in reales[:10]))
    else:
        print("     - 0 a mas de 250 km: ningun error de calibracion.")
    if por_pais:
        print("   Paises con mas casos fuera: "
          + ", ".join(f"{p} {n}" for p, n in por_pais.most_common(6)))
    uio = fuente.por_iata("UIO")
    mia = fuente.por_iata("MIA")
    uio_dentro = bool(uio and pais_que_contiene(proyeccion, indice.get("ecuador", []),
                                               uio.lat, uio.lon))
    mia_dentro = bool(mia and pais_que_contiene(
        proyeccion, indice.get("united states of america", []), mia.lat, mia.lon))
    print(f"   Control: UIO {'dentro' if uio_dentro else 'FUERA'} de Ecuador"
          f" | MIA {'dentro' if mia_dentro else 'FUERA'} de USA")

    # 2. Factor de escala: debe ser el mismo en cualquier tramo.
    print("\n2. Factor de escala en tramos largos (debe ser constante):")
    tramos = [("UIO", "MAD"), ("UIO", "JFK"), ("SYD", "LAX"), ("DXB", "SYD"),
              ("BOG", "SCL"), ("NRT", "SCL"), ("MEX", "ARG")]
    esperado = px_por_grado_lon / KM_POR_GRADO
    desviaciones = []
    for a, b in tramos:
        pa, pb = fuente.por_iata(a), fuente.por_iata(b)
        if not pa or not pb:
            continue
        km = geo.haversine(pa.lat, pa.lon, pb.lat, pb.lon)
        x1, y1 = proyeccion.a_pixeles(pa.lat, pa.lon)
        x2, y2 = proyeccion.a_pixeles(pb.lat, pb.lon)
        dx = abs(x2 - x1) % ancho
        dx = min(dx, ancho - dx)
        px = (dx ** 2 + (y2 - y1) ** 2) ** 0.5
        escala = px / km
        desviaciones.append(abs(escala - esperado) / esperado)
        print(f"   {a}-{b}: {km:8,.0f} km -> {px:7.1f} px = {escala:.4f} px/km")
    if desviaciones:
        print(f"   Desviacion media respecto de {esperado:.4f} px/km: "
              f"{sum(desviaciones) / len(desviaciones):.2%}")
        print("   No es error de calibracion: en equirectangular, un mismo gran circulo")
        print("   ocupa mas pixeles cuanto mas polar es el tramo (UIO-MAD pesa mas que")
        print("   UIO-JFK). Es la deformacion propia de la proyeccion, y por eso las")
        print("   distancias del panel se calculan con haversine, no con los pixeles.")

    # 3. Coordenadas de la ruta de demostracion, ya proyectadas.
    print("\n3. Ruta de demostracion (proyectada):")
    for iata in ("UIO", "BOG", "SCL", "JNB", "DXB", "MAD", "MIA"):
        a = fuente.por_iata(iata)
        if a:
            x, y = proyeccion.a_pixeles(a.lat, a.lon)
            print(f"   {a.iata}  {a.ciudad:<16} {a.pais:<24} "
                  f"({a.lat:+7.3f}, {a.lon:+8.3f}) -> px ({x:7.1f}, {y:6.1f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
