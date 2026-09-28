"""
calibrar_mapa.py - Georreferencia la imagen base del simulador.

AVISO: este script es un archivo historico. Audita la proyeccion
declarada comparando `imagen.png` con los paises de Natural Earth.
El simulador ya no dibuja esa imagen: el mapa es la capa vectorial.
Se conserva para poder mostrar de donde salio el origen de -30 grados.
Problema: `imagen.png` es una ilustracion de 1800x913 px sin proyeccion
declarada, y la version de muestra situaba los paises en pixeles inventados.
Este script determina los parametros de la proyeccion (desplazamiento de
longitud y rango de latitud) comparando la mascara de tierra de la imagen con
los poligonos reales de Natural Earth.

Metodo (es el ajuste por minimos cuadrados de la practica, aqui por
maximizacion de indice de Interseccion sobre Union):

    IoU = |mascara_imagen ∩ proyeccion( Natural Earth )| / |union|

Se recorren candidatos de desplazamiento de longitud y de rango de latitud; el
mejor se guarda en data/calibracion_mapa.json y la aplicacion lo usa al
arrancar. Asi la calibracion es reproducible y auditable, no un numero
escrito a mano.

Uso:
    python herramientas/calibrar_mapa.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
IMAGEN = RAIZ / "imagen.png"
PAISES = RAIZ / "data" / "paises.geojson"
SALIDA = RAIZ / "data" / "calibracion_mapa.json"

# La imagen tiene esquinas redondeadas: el recorte en alfa se descarta.
UMBRAL_ALFA = 128
COLS, FILAS = 180, 92


def mascara_tierra(ruta: Path) -> list[list[bool]]:
    """Clasifica cada celda de la imagen como tierra (1) u oceano/hielo (0)."""
    with Image.open(ruta) as imagen:
        alpha = imagen.getchannel("A") if imagen.mode == "RGBA" else None
        muestra = imagen.convert("RGB").resize((COLS, FILAS), Image.BOX)
    pixeles = muestra.load()
    alfa = alpha.resize((COLS, FILAS), Image.BOX).load() if alpha else None

    mascara: list[list[bool]] = []
    for y in range(FILAS):
        fila = []
        for x in range(COLS):
            r, g, b = pixeles[x, y]
            if alfa is not None and alfa[x, y] < UMBRAL_ALFA:
                fila.append(False)          # esquina redondeada
            elif r > 235 and g > 235 and b > 235:
                fila.append(False)          # hielo (Greenland, Antartida)
            elif b > r + 12:
                fila.append(False)          # oceano
            else:
                fila.append(True)           # tierra
        mascara.append(fila)
    return mascara


def cargar_anillos(ruta: Path) -> list[list[tuple[float, float]]]:
    """Anillos exteriores de los paises, en (lon, lat)."""
    with ruta.open(encoding="utf-8") as archivo:
        geojson = json.load(archivo)
    anillos: list[list[tuple[float, float]]] = []
    for feature in geojson.get("features", []):
        geometria = feature.get("geometry") or {}
        coordenadas = geometria.get("coordinates") or []
        politonos = ([coordenadas] if geometria.get("type") == "Polygon"
                     else coordenadas if geometria.get("type") == "MultiPolygon" else [])
        for poligono in politonos:
            for anillo in poligono:
                if len(anillo) >= 4:
                    anillos.append([(c[0], c[1]) for c in anillo])
    return anillos


def proyectar(anillos, lon_izq: float, lat_sup: float, lat_inf: float) -> list[list[bool]]:
    """Rasteriza los anillos con una proyeccion equirectangular candidata."""
    alto_grados = lat_sup - lat_inf
    latitudes = [lat_sup - (y / (FILAS - 1)) * alto_grados for y in range(FILAS)]
    mascara: list[list[bool]] = [[False] * COLS for _ in range(FILAS)]

    for anillo in anillos:
        x = [((lon - lon_izq) % 360.0) / 360.0 * COLS for lon, _ in anillo]
        y = [lat for _, lat in anillo]
        filas = [i for i, lat in enumerate(latitudes) if min(y) <= lat <= max(y)]
        if len(filas) < 2:
            continue
        for fila in range(filas[0], filas[-1] + 1):
            lat = latitudes[fila]
            cruces = []
            for i in range(len(anillo)):
                j = (i + 1) % len(anillo)
                y1, y2 = y[i], y[j]
                if (y1 <= lat < y2) or (y2 <= lat < y1):
                    t = (lat - y1) / (y2 - y1)
                    cruces.append(x[i] + (x[j] - x[i]) * t)
            if len(cruces) < 2:
                continue
            cruces.sort()
            for a in range(0, len(cruces) - 1, 2):
                desde = max(0, math.ceil(cruces[a] - 0.5))
                hasta = min(COLS - 1, math.floor(cruces[a + 1] - 0.5))
                for columna in range(desde, hasta + 1):
                    mascara[fila][columna] = True
    return mascara


def iou(observada: list[list[bool]], candidata: list[list[bool]]) -> tuple[float, int, int]:
    interseccion = union = 0
    for y in range(FILAS):
        for x in range(COLS):
            a, b = observada[y][x], candidata[y][x]
            interseccion += a and b
            union += a or b
    return (interseccion / union if union else 0.0), interseccion, union


def buscar(anillos, observada) -> tuple[float, float, float, float]:
    """Explora desplazamientos de longitud y rangos de latitud."""
    mejor = (0.0, 0.0, 90.0, -90.0)
    historial = []
    for lon_izq in range(-180, 180, 2):
        for lat_sup, lat_inf in ((90.0, -90.0), (85.0, -85.0), (84.0, -84.0), (88.0, -88.0)):
            mascara = proyectar(anillos, float(lon_izq), lat_sup, lat_inf)
            puntaje, inter, union = iou(observada, mascara)
            historial.append((puntaje, lon_izq, lat_sup, lat_inf, inter, union))
            if puntaje > mejor[0]:
                mejor = (puntaje, float(lon_izq), lat_sup, lat_inf)
    historial.sort(reverse=True)
    return mejor, historial


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--top", type=int, default=6, help="cuantos candidatos mostrar")
    argumentos = analizador.parse_args()

    if not IMAGEN.exists() or not PAISES.exists():
        print("Faltan imagen.png o data/paises.geojson. Ejecute preparar_datos.py.",
              file=sys.stderr)
        return 1

    print("1/4 Extrayendo la mascara de tierra de imagen.png ...")
    observada = mascara_tierra(IMAGEN)
    tierra = sum(sum(fila) for fila in observada)
    print(f"      tierra detectada: {tierra} celdas ({tierra / (COLS * FILAS):.1%})")

    print("2/4 Cargando contornos de Natural Earth ...")
    anillos = cargar_anillos(PAISES)
    print(f"      {len(anillos)} anillos, {sum(len(a) for a in anillos)} vertices")

    print("3/4 Buscando la proyeccion que mejor se ajusta (maximizando IoU) ...")
    mejor, historial = buscar(anillos, observada)
    puntaje, lon_izq, lat_sup, lat_inf = mejor

    print(f"      mejor IoU = {puntaje:.3f}  con  longitud {lon_izq:+.0f}°  "
          f"y  latitud {lat_sup:+.0f}° a {lat_inf:+.0f}°")
    print("      otros candidatos:")
    for p, lon, ls, li, inter, union in historial[1:argumentos.top]:
        print(f"        IoU={p:.3f}  lon={lon:+4d}  lat={ls:+.0f}..{li:+.0f}")

    print("4/4 Guardando data/calibracion_mapa.json ...")
    SALIDA.write_text(json.dumps({
        "proyeccion": "equirectangular",
        "lon_izquierda": lon_izq,
        "longitud_grados": 360.0,
        "latitud_superior": lat_sup,
        "latitud_inferior": lat_inf,
        "imagen_px": [COLS * 10, FILAS * 10],
        "iou": round(puntaje, 4),
        "metodo": "maximizacion de IoU sobre Natural Earth 110m",
    }, indent=2), encoding="utf-8")
    print(f"      escrito en {SALIDA.relative_to(RAIZ)}")
    print(f"\nUse estos valores como LONGITUD_IZQUIERDA / LATITUD_SUPERIOR / "
          f"LATITUD_INFERIOR en ihc/app.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
