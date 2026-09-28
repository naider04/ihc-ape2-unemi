"""
generar_fondo.py - Genera la imagen de fondo del mapa y su referencia.

El mapa del simulador es una lamina de 1800 x 913 px con proyeccion
equirectangular declarada: el borde izquierdo es 30 grados oeste y el derecho
30 grados este, y la lamina va de 90 N a 90 S. Esa declaracion es lo que permite
construir una imagen que case con las lineas sin tantear: la tierra de la imagen
tiene que caer donde el simulador pone la tierra.

Este script produce tres cosas en `referencias/`:

  1. `mapa_<ancho>x<alto>.png`  la silueta de la tierra rellena, con el oceano de
     un color y la tierra de otro. Es la referencia que hay que enseñarle a
     quien dibuje el fondo: si su imagen tiene las mismas siluetas en los mismos
     pixeles, encaja.
  2. `mapa_<ancho>x<alto>_rejilla.png`  lo mismo con la cuadricula de latitud y
     longitud cada 15 grados y las etiquetas en los bordes. Sirve para
     comprobar o corregir a mano la alineacion de la imagen que se reciba.
  3. `fondo_<ancho>x<alto>.png`  un fondo listo para usar, dibujado con los
     propios datos del simulador: oceano degradado, tierra con relieve y una
     linea de costa mas marcada. No necesita a nadie para generarlo, y como sale
     de la misma proyeccion que las lineas, encaja por construccion.

El alto no se elige: sale del ancho. La lamina es de 180 x 180 grados, asi que
alto = round(ancho * 913 / 1800). Con ancho 1800 sale 913, con 3600 sale 1826.

Uso:
    python herramientas/generar_fondo.py                    # 1800 x 913
    python herramientas/generar_fondo.py --ancho 3600        # el doble, para
                                                             # que al acercar
                                                             # el mapa no se vea
                                                             # borroso
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from ihc.proyeccion import Limites, Proyeccion  # noqa: E402

# --- los mismos limites que usa la app (data/calibracion_mapa.json) ----------
LIMITES = Limites(-30.0, 330.0, 90.0, -90.0)
GRADOS_LAT = LIMITES.alto          # 180
GRADOS_LON = LIMITES.ancho         # 360
# El alto de la lamina sobre el ancho original de 1800 px x 913 px. Es 0,50722,
# no 0,5: la lamina es algo mas alta que la mitad, y esa diferencia son 13 px.
ALTO_POR_ANCHO = 913.0 / 1800.0

SALIDA = RAIZ / "referencias"

OCEANO = (24, 62, 104)
OCEANO_CLARO = (38, 92, 140)
TIERRA = (226, 214, 184)
TIERRA_BORDE = (150, 138, 110)
COSTA = (92, 82, 62)
REJILLA = (255, 90, 90)
REJILLA_PUNTO = (255, 170, 170)


def tamano(ancho: int) -> tuple[int, int]:
    return ancho, round(ancho * ALTO_POR_ANCHO)


def cargar_anillos() -> list[list[list[tuple[float, float]]]]:
    """Anillos de todos los paises como (lon, lat) en grados, sin simplificar.

    Se usan los datos crudos, no `data/paises.json`, porque la silueta de
    referencia tiene que ser fiel: aqui no se aligera nada.
    """
    import json

    ruta = RAIZ / "data" / "paises.geojson"
    if not ruta.exists():
        raise SystemExit(
            "Falta data/paises.geojson. Ejecute: python herramientas/preparar_datos.py")
    with ruta.open(encoding="utf-8") as archivo:
        geojson = json.load(archivo)

    paises: list[list[list[tuple[float, float]]]] = []
    for feature in geojson.get("features", []):
        geometria = feature.get("geometry")
        if not geometria:
            continue
        if geometria["type"] == "Polygon":
            anillos = [geometria["coordinates"][0]]
        elif geometria["type"] == "MultiPolygon":
            anillos = [poligono[0] for poligono in geometria["coordinates"]]
        else:
            continue
        for anillo in anillos:
            if len(anillo) >= 4:
                paises.append([(c[0], c[1]) for c in anillo])
    return paises


def proyectar(proyeccion: Proyeccion, puntos: list[tuple[float, float]]
              ) -> list[tuple[float, float]]:
    """(lon, lat) -> (x, y) en pixeles de la lamina.

    `a_pixeles` espera (lat, lon), igual que en el simulador, y usa el modulo
    para el salto del antimeridiano. Es la misma cuenta que hace la app, que es
    justo lo que hace que las dos cosas encajen.
    """
    return [proyeccion.a_pixeles(lat, lon) for lon, lat in puntos]


def dibujar_Referencia(ancho: int, salida: Path) -> Path:
    """Silueta tierra/oceano, la referencia de forma."""
    alto = tamano(ancho)[1]
    proyeccion = Proyeccion(LIMITES, float(ancho), float(alto))
    imagen = Image.new("RGB", (ancho, alto), OCEANO)
    lienzo = ImageDraw.Draw(imagen)
    for anillo in cargar_anillos():
        lienzo.polygon(proyectar(proyeccion, anillo), fill=TIERRA, outline=TIERRA_BORDE)
    imagen.save(salida)
    return salida


def dibujar_rejilla(ancho: int, salida: Path) -> Path:
    """La referencia con cuadricula y etiquetas de latitud y longitud."""
    alto = tamano(ancho)[1]
    base = dibujar_referencia_en_memoria(ancho)
    lienzo = ImageDraw.Draw(base, "RGBA")
    fuente = _fuente(max(11, ancho // 110))
    px_por_grado_lon = ancho / GRADOS_LON
    px_por_grado_lat = alto / GRADOS_LAT

    for lon in range(-180, 181, 15):
        x = ((lon - LIMITES.lon_izq) % 360.0) / GRADOS_LON * ancho
        for copia in (0, ancho):
            lienzo.line([(x + copia, 0), (x + copia, alto)], fill=REJILLA, width=1)
        if lon % 30 == 0:
            etiqueta = f"{lon:+d}°".replace("+0°", "0°")
            ancho_texto = lienzo.textlength(etiqueta, font=fuente)
            for copia in (0, ancho):
                lienzo.text((x + copia + 3, alto - fuente.size - 3), etiqueta,
                            fill=REJILLA, font=fuente)

    for lat in range(-90, 91, 15):
        y = (LIMITES.lat_sup - lat) / GRADOS_LAT * alto
        lienzo.line([(0, y), (ancho, y)], fill=REJILLA, width=1)
        if lat % 30 == 0:
            etiqueta = f"{lat:+d}°".replace("+0°", "0°")
            for y_texto in (3, alto - fuente.size - 3):
                marco = Image.new("RGBA", (int(lienzo.textlength(etiqueta, font=fuente)) + 4,
                                            fuente.size + 4), (255, 255, 255, 200))
                ImageDraw.Draw(marco).text((2, 2), etiqueta, fill=(120, 0, 0), font=fuente)
                base.paste(marco, (3, int(y_texto)), marco)

    # las cuatro esquinas, para que se vea de donde parte el mapa
    for (x, y, etiqueta) in ((0, 0, f"izq {LIMITES.lon_izq:+.0f}°"),
                             (ancho - 120, 0, f"der {LIMITES.lon_der:+.0f}°"),
                             (0, alto - 2 * fuente.size, f"sup {LIMITES.lat_sup:+.0f}°")):
        lienzo.text((x + 3, y + 3), etiqueta, fill=REJILLA, font=fuente)

    base.save(salida)
    return salida


def dibujar_fondo(ancho: int, salida: Path) -> Path:
    """Fondo listo para usar: oceano degradado, tierra con sombra en la costa.

    Sale de los mismos poligonos y de la misma proyeccion que las lineas del
    simulador, asi que encaja por construccion y no hay que ajustar nada.
    """
    alto = tamano(ancho)[1]
    proyeccion = Proyeccion(LIMITES, float(ancho), float(alto))
    anillos = cargar_anillos()

    # 1. Oceano: degradado vertical, mas oscuro hacia los polos.
    oceano = Image.new("RGB", (1, alto))
    pixeles = oceano.load()
    for y in range(alto):
        t = abs(y / (alto - 1) - 0.5) * 2.0            # 0 en el ecuador, 1 en los polos
        t = t ** 1.4
        pixeles[0, y] = tuple(round(OCEANO_CLARO[c] + (OCEANO[c] - OCEANO_CLARO[c]) * t)
                              for c in range(3))
    imagen = oceano.resize((ancho, alto))

    # 2. Mascara de tierra, y versions desenfocada y erosionada de la misma.
    mascara = Image.new("L", (ancho, alto), 0)
    lienzo = ImageDraw.Draw(mascara)
    proyectados = [proyectar(proyeccion, a) for a in anillos]
    for puntos in proyectados:
        lienzo.polygon(puntos, fill=255)
    difusa = mascara.filter(ImageFilter.GaussianBlur(max(1.0, ancho / 500.0)))

    # 3. Tierra plana, con una banda de sombra difusa justo en la costa: da la
    #    sensacion de altura sin ensuciar el interior.
    # `composite` toma el primer color donde la mascara es blanca: la tierra
    # llana va en el interior de la mascara difusa y el tono de sombra en la
    # franja que rodea la costa, que es lo que da el relieve.
    tierra = Image.new("RGB", (ancho, alto), TIERRA)
    con_relieve = Image.composite(tierra, Image.new("RGB", (ancho, alto), TIERRA_BORDE),
                                  difusa)
    tierra.paste(con_relieve, (0, 0), mascara)
    imagen.paste(tierra, (0, 0), mascara)

    # 4. Linea de costa marcada, un pelo mas clara que la sombra.
    lienzo = ImageDraw.Draw(imagen)
    grosor = max(1, round(ancho / 1400))
    for puntos in proyectados:
        lienzo.line(puntos + [puntos[0]], fill=COSTA, width=grosor, joint="curve")

    imagen.save(salida)
    return salida


# --- utilidades -------------------------------------------------------------

def dibujar_referencia_en_memoria(ancho: int) -> Image.Image:
    alto = tamano(ancho)[1]
    proyeccion = Proyeccion(LIMITES, float(ancho), float(alto))
    imagen = Image.new("RGB", (ancho, alto), OCEANO)
    lienzo = ImageDraw.Draw(imagen)
    for anillo in cargar_anillos():
        lienzo.polygon(proyectar(proyeccion, anillo), fill=TIERRA, outline=TIERRA_BORDE)
    return imagen


def _fuente(tamano_px: int) -> ImageFont.ImageFont:
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "/usr/share/fonts/TTF/DejaVuSans.ttf"):
        if Path(ruta).exists():
            try:
                return ImageFont.truetype(ruta, tamano_px)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__,
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
    analizador.add_argument("--ancho", type=int, default=1800,
                            help="ancho en px; el alto sale del ancho (913/1800)")
    argumentos = analizador.parse_args()
    if argumentos.ancho < 200:
        print("El ancho tiene que ser al menos 200 px.", file=sys.stderr)
        return 1

    SALIDA.mkdir(parents=True, exist_ok=True)
    ancho = argumentos.ancho
    alto = tamano(ancho)[1]
    etiqueta = f"{ancho}x{alto}"
    print(f"Lamina {etiqueta} px  |  {GRADOS_LON:.0f}° de longitud x {GRADOS_LAT:.0f}° de latitud")
    print(f"        {ancho / GRADOS_LON:.4f} px por grado de longitud, "
          f"{alto / GRADOS_LAT:.4f} px por grado de latitud")
    print(f"        borde izquierdo en {LIMITES.lon_izq:+.0f}°, derecho en {LIMITES.lon_der:+.0f}°\n")

    for ruta in (dibujar_Referencia(ancho, SALIDA / f"mapa_{etiqueta}.png"),
                 dibujar_rejilla(ancho, SALIDA / f"mapa_{etiqueta}_rejilla.png"),
                 dibujar_fondo(ancho, SALIDA / f"fondo_{etiqueta}.png")):
        print(f"  {ruta.relative_to(RAIZ)}")
        with Image.open(ruta) as imagen:
            print(f"     {imagen.width} x {imagen.height} px, {ruta.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
