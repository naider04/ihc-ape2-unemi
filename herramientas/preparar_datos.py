"""
preparar_datos.py - Descarga y normaliza los recursos geograficos del simulador.

Este script es el paso "Gestion de Recursos" de la guia: baja una sola vez las
fuentes publicas de datos, las limpia y las guarda en ./data para que la
aplicacion funcione luego SIN internet (requisito para la evidencia de consola
limpia durante la demostracion).

Uso:
    python herramientas/preparar_datos.py            # descarga lo que falte
    python herramientas/preparar_datos.py --fuerza   # vuelve a descargarlo todo

Fuentes (datos de dominio publico):
  * Aeropuertos : https://github.com/davidmegginson/ourairports-data
  * Paises      : https://github.com/nvkelso/natural-earth-vector
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_DATOS = RAIZ / "data"

URL_AEROPUERTOS = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
)
URL_PAISES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_50m_admin_0_countries.geojson"
)

CSV_BRUTO = CARPETA_DATOS / "ourairports_airports.csv"
CSV_LIMPIO = CARPETA_DATOS / "aeropuertos.csv"
GEOJSON_PAISES = CARPETA_DATOS / "paises.geojson"
JSON_PAISES = CARPETA_DATOS / "paises.json"

# Solo interesan los aeropuertos con codigo IATA y tipo grande/medio: son los
# que un pasajero puede realistically elegir como origen o destino.
TIPOS_UTILES = {"large_airport", "medium_airport"}
CAMPOS_SALIDA = [
    "iata", "icao", "nombre", "ciudad", "pais", "iso_pais",
    "continente", "lat", "lon", "elevacion_ft", "tipo",
]


def descargar(url: str, destino: Path, forzar: bool = False) -> bool:
    """Descarga `url` a `destino`. Devuelve True si el archivo quedo disponible."""
    if destino.exists() and destino.stat().st_size > 0 and not forzar:
        print(f"  [ok]  ya existe {destino.name} ({destino.stat().st_size:,} bytes)")
        return True
    print(f"  [get] {url}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as respuesta:
            datos = respuesta.read()
    except OSError as error:  # sin red, DNS, etc.
        print(f"  [ERR] no se pudo descargar: {error}", file=sys.stderr)
        return False
    destino.write_bytes(datos)
    print(f"  [ok]  {destino.name} ({len(datos):,} bytes)")
    return True


def cargar_nombres_pais() -> dict[str, str]:
    """codigo ISO -> nombre de pais, tomado de Natural Earth.

    OurAirports usa ISO 3166-1 alfa-2 ("EC") y Natural Earth tambien publica
    ese campo, de modo que la union es directa. Se guarda tambien el alfa-3
    como alternativa para los pocos casos en que falta el alfa-2.
    """
    if not JSON_PAISES.exists():
        return {}
    datos = json.loads(JSON_PAISES.read_text(encoding="utf-8"))
    nombres: dict[str, str] = {}
    for feature in datos.get("features", []):
        nombre = feature.get("nombre", "?")
        for clave in ("iso", "iso3"):
            codigo = feature.get(clave, "")
            if codigo:
                nombres.setdefault(codigo, nombre)
    return nombres


def limpiar_aeropuertos(origen: Path, destino: Path) -> int:
    """Filtra el CSV de OurAirports y escribe un CSV compacto y estable."""
    nombres_pais = cargar_nombres_pais()
    filas: list[dict] = []
    with origen.open(newline="", encoding="utf-8") as archivo:
        for registro in csv.DictReader(archivo):
            if registro.get("type") not in TIPOS_UTILES:
                continue
            iata = (registro.get("iata_code") or "").strip()
            if not iata:
                continue
            iso_pais = (registro.get("iso_country") or "").strip()
            try:
                lat = float(registro["latitude_deg"])
                lon = float(registro["longitude_deg"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            try:
                elevacion = int(float(registro.get("elevation_ft") or 0))
            except ValueError:
                elevacion = 0
            filas.append(
                {
                    "iata": iata.upper(),
                    "icao": (registro.get("icao_code") or "").upper(),
                    "nombre": (registro.get("name") or "").strip(),
                    "ciudad": (registro.get("municipality") or "").strip(),
                    "pais": nombres_pais.get(iso_pais, iso_pais),
                    "iso_pais": iso_pais,
                    "continente": (registro.get("continent") or "").strip(),
                    "lat": f"{lat:.5f}",
                    "lon": f"{lon:.5f}",
                    "elevacion_ft": elevacion,
                    "tipo": registro["type"],
                }
            )

    filas.sort(key=lambda f: f["iata"])
    with destino.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=CAMPOS_SALIDA)
        escritor.writeheader()
        escritor.writerows(filas)
    return len(filas)


# Lado minimo, en grados, de un anillo para conservarlo. 0,5 grados son unos
# 55 km: por debajo de eso la silueta es un punto y solo anade coste de dibujo.
LADO_MINIMO_ANILLO = 0.5


def _cabe_en_pantalla(anillo: list[list[float]]) -> bool:
    """El anillo abarca al menos medio grado en alguna direccion?"""
    xs = [c[0] for c in anillo]
    ys = [c[1] for c in anillo]
    return (max(xs) - min(xs)) >= LADO_MINIMO_ANILLO or \
           (max(ys) - min(ys)) >= LADO_MINIMO_ANILLO


def resumir_paises(origen: Path, destino: Path) -> int:
    """Reduce el GeoJSON de paises: solo anillos y nombre, sin metadatos inutiles."""
    with origen.open(encoding="utf-8") as archivo:
        geojson = json.load(archivo)

    features = []
    for feature in geojson.get("features", []):
        geometria = feature.get("geometry")
        if not geometria:
            continue
        anillos: list[list[list[float]]] = []
        if geometria["type"] == "Polygon":
            anillos = [ring for ring in geometria["coordinates"] if len(ring) >= 4]
        elif geometria["type"] == "MultiPolygon":
            for poligono in geometria["coordinates"]:
                anillos.extend(ring for ring in poligono if len(ring) >= 4)
        if not anillos:
            continue
        # Descarta el detalle que no se ve, pero sin perder territorio de verdad.
        # Antes se quedaban los 4 anillos con mas vertices y eso borraba a
        # las islas de un pais que tuviera muchas: en 50m Estados Unidos tiene
        # 127 poligonos y Hawai se caia de los 4 primeros. Ahora se conservan
        # siempre el mayor (para que un pais enano no desaparezca entero) y todos
        # los que ocupan medio grado o mas, que a esta escala si se dibujan.
        anillos = [r for r in anillos if _cabe_en_pantalla(r)] or anillos[:1]
        anillos.sort(key=len, reverse=True)
        propiedades = feature.get("properties", {})
        features.append(
            {
                "nombre": propiedades.get("NAME", "?"),
                "iso": propiedades.get("ISO_A2") or propiedades.get("ADM0_A3") or "",
                "iso3": propiedades.get("ISO_A3") or propiedades.get("ADM0_A3") or "",
                "continente": propiedades.get("CONTINENT", "?"),
                "anillos": anillos,
            }
        )

    destino.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":")),
        encoding="utf-8",
    )
    return len(features)


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--fuerza", action="store_true", help="redisenar los archivos")
    argumentos = analizador.parse_args()

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    print("1/3 Paises (Natural Earth 50m)")
    if descargar(URL_PAISES, GEOJSON_PAISES, argumentos.fuerza):
        n = resumir_paises(GEOJSON_PAISES, JSON_PAISES)
        print(f"  [ok]  paises.json con {n} paises")

    print("2/3 Aeropuertos (OurAirports)")
    if not descargar(URL_AEROPUERTOS, CSV_BRUTO, argumentos.fuerza):
        print("AVISO: sin CSV original se usara la cache previa.", file=sys.stderr)

    print("3/3 Filtro de aeropuertos utilizables")
    if CSV_BRUTO.exists():
        total = limpiar_aeropuertos(CSV_BRUTO, CSV_LIMPIO)
        print(f"  [ok]  aeropuertos.csv con {total:,} aeropuertos (grande/medio con IATA)")
    else:
        print("  [ERR] no hay CSV de origen.", file=sys.stderr)
        return 1

    print("\nListo. La aplicacion ya puede ejecutarse sin internet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
