"""
ihc.datos - Carga de los recursos del simulador (aeropuertos y paises).

Reglas de diseño:
  * Los datos viven en ./data y se leen SIN conexion (la maquina del
    laboratorio puede no tener internet en la demostracion).
  * Si falta un recurso, la aplicacion NO se cae: entra en modo degradado con
    una lista minima de aeropuertos y lo avisa en la barra de estado. Es la
    diferencia entre "consola de errores limpia" y un traceback en pantalla.
"""

from __future__ import annotations

import csv
import json
import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Sequence

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
CARPETA_DATOS = RAIZ_PROYECTO / "data"

def normalizar(texto: str) -> str:
    """Mayusculas sin tildes: «España» y «ESPANA» deben ser la misma busqueda."""
    plano = unicodedata.normalize("NFKD", texto.strip().upper())
    return "".join(c for c in plano if not unicodedata.combining(c))


# Natural Earth publica los paises en ingles y la interfaz esta en espanol.
# Sin este diccionario, escribir «Japon» o «Suiza» no encuentra nada.
ALIAS_PAIS: dict[str, str] = {
    "ALEMANIA": "GERMANY", "ARGENTINA": "ARGENTINA", "AUSTRALIA": "AUSTRALIA",
    "AUSTRIA": "AUSTRIA", "BELGICA": "BELGIUM", "BOLIVIA": "BOLIVIA",
    "BOSNIA": "BOSNIA", "BRASIL": "BRAZIL", "BULGARIA": "BULGARIA",
    "CANADA": "CANADA", "CHILE": "CHILE", "CHINA": "CHINA", "COLOMBIA": "COLOMBIA",
    "COSTA RICA": "COSTA RICA", "CROACIA": "CROATIA", "CUBA": "CUBA",
    "DINAMARCA": "DENMARK", "ECUADOR": "ECUADOR", "EGIPTO": "EGYPT",
    "EL SALVADOR": "EL SALVADOR", "ESLOVAQUIA": "SLOVAKIA", "ESLOVENIA": "SLOVENIA",
    "ESPANA": "SPAIN", "ESTADOS UNIDOS": "UNITED STATES OF AMERICA",
    "ESTONIA": "ESTONIA", "ETIOPIA": "ETHIOPIA", "FILIPINAS": "PHILIPPINES",
    "FINLANDIA": "FINLAND", "FRANCIA": "FRANCE", "GEORGIA": "GEORGIA",
    "GRECIA": "GREECE", "HUNGRIA": "HUNGARY", "INDIA": "INDIA", "IRAN": "IRAN",
    "IRLANDA": "IRELAND", "ISLANDIA": "ICELAND", "ISRAEL": "ISRAEL",
    "ITALIA": "ITALY", "JAPON": "JAPAN", "JORDANIA": "JORDAN",
    "KAZAJSTAN": "KAZAKHSTAN", "KENIA": "KENYA", "KUWAIT": "KUWAIT",
    "LEBANIA": "LEBANON", "LITUANIA": "LITHUANIA", "LUXEMBURGO": "LUXEMBOURG",
    "MALASIA": "MALAYSIA", "MARRUECOS": "MOROCCO", "MEXICO": "MEXICO",
    "NICARAGUA": "NICARAGUA", "NORUEGA": "NORWAY", "NUEVA ZELANDA": "NEW ZEALAND",
    "PAISES BAJOS": "NETHERLANDS", "PANAMA": "PANAMA", "PARAGUAY": "PARAGUAY",
    "PERU": "PERU", "POLONIA": "POLAND", "PORTUGAL": "PORTUGAL",
    "REINO UNIDO": "UNITED KINGDOM", "REPUBLICA DOMINICANA": "DOMINICAN REPUBLIC",
    "RUMANIA": "ROMANIA", "RUSIA": "RUSSIA", "SENEGAL": "SENEGAL",
    "SERBIA": "SERBIA", "SINGAPUR": "SINGAPORE", "SUECIA": "SWEDEN",
    "SUIZA": "SWITZERLAND", "TAILANDIA": "THAILAND", "TURQUIA": "TURKEY",
    "UCRANIA": "UKRAINE", "URUGUAY": "URUGUAY", "VIETNAM": "VIETNAM",
}

# Las ciudades tambien estan en ingles en los datos de origen.
ALIAS_CIUDAD: dict[str, str] = {
    "BOMBAY": "MUMBAI", "DELHI": "NEW DELHI", "EL CAIRO": "CAIRO",
    "LONDRES": "LONDON", "MANILA": "MANILA", "MOSCU": "MOSCOW",
    "NUEVA YORK": "NEW YORK", "PEKIN": "BEIJING", "RIO DE JANEIRO": "RIO DE JANEIRO",
    "SAN FRANCISCO": "SAN FRANCISCO", "SAO PAULO": "SAO PAULO", "SEUL": "SEOUL",
}

# Lista minima de respaldo: doce aeropuertos fijados a mano, para que la
# aplicacion siga siendo utilizable aunque falte el CSV de OurAirports.
AEROPUERTOS_DE_RESPALDO: tuple[tuple[str, str, str, str, float, float], ...] = (
    ("Ecuador", "UIO", "Mariscal Sucre", "Quito", -0.1254, -78.3543),
    ("Estados Unidos", "MIA", "Miami International", "Miami", 25.7959, -80.2870),
    ("Estados Unidos", "JFK", "John F. Kennedy", "Nueva York", 40.6413, -73.7781),
    ("España", "MAD", "Adolfo Suárez Madrid-Barajas", "Madrid", 40.4936, -3.5728),
    ("España", "BCN", "El Prat", "Barcelona", 41.2974, 2.0833),
    ("Colombia", "BOG", "El Dorado", "Bogotá", 4.7016, -74.1469),
    ("Perú", "LIM", "Jorge Chávez", "Lima", -12.0219, -77.1143),
    ("Brasil", "GRU", "Guarulhos", "São Paulo", -23.4356, -46.4731),
    ("México", "MEX", "Benito Juárez", "Ciudad de México", 19.4363, -99.0721),
    ("Japón", "HND", "Haneda", "Tokio", 35.5494, 139.7798),
    ("Australia", "SYD", "Kingsford Smith", "Sídney", -33.9399, 151.1753),
    ("Sudáfrica", "JNB", "O.R. Tambo", "Johannesburgo", -26.1367, 28.2411),
)


@dataclass(frozen=True)
class Aeropuerto:
    """Aeropuerto con su posicion geografica real."""

    iata: str
    nombre: str
    ciudad: str
    pais: str
    lat: float
    lon: float
    icao: str = ""
    elevacion_ft: int = 0
    tipo: str = ""

    @property
    def etiqueta(self) -> str:
        """Texto para la etiqueta del mapa: codigo + ciudad."""
        return f"{self.iata} · {self.ciudad or self.nombre}"

    @property
    def descripcion(self) -> str:
        partes = [self.nombre, self.ciudad, self.pais]
        return " — ".join(p for p in partes if p)

    @property
    def elevacion_m(self) -> int:
        return round(self.elevacion_ft * 0.3048)


@dataclass(frozen=True)
class Pais:
    nombre: str
    iso: str
    anillos: Sequence[Sequence[Sequence[float]]]


# Desviacion maxima admisible al simplificar un contorno, en grados.
# Natural Earth 50m trae 99.613 vertices para 242 paises y cada uno se dibuja en
# cada fotograma, asi que hay que aligerarlo. A 0,2 grados quedan 10.361 vertices,
# algo mas que los 7.875 de la 110m, y el desplazamiento es de 6 px con el
# acercamiento maximo, que no se aprecia: solo se ve la linea al ganhar detalle.
# Con la 110m los vertices eran menos, pero sus costas erraban tanto que los
# aeropuertos de costa caian en el mar.
TOLERANCIA_CONTORNOS = 0.2


def simplificar_anillo(anillo: Sequence[Sequence[float]],
                       tolerancia: float = TOLERANCIA_CONTORNOS
                       ) -> list[tuple[float, float]]:
    """Reduce los vertices de un contorno con Douglas-Peucker.

    Se aplica al cargar, no al dibujar: `paises.json` conserva los datos
    originales y solo la version que se pinta se simplifica. La pila es
    explicita porque Canada y Rusia tienen anillos de mas de mil vertices, que
    superarian el limite de recursividad de Python.
    """
    puntos = [(float(p[0]), float(p[1])) for p in anillo]
    if len(puntos) < 4 or tolerancia <= 0:
        return puntos
    limites = [(0, len(puntos) - 1)]
    conservar = [False] * len(puntos)
    conservar[0] = conservar[-1] = True
    while limites:
        primero, ultimo = limites.pop()
        if ultimo <= primero + 1:
            continue
        x1, y1 = puntos[primero]
        x2, y2 = puntos[ultimo]
        dx, dy = x2 - x1, y2 - y1
        norma = dx * dx + dy * dy
        peor, peor_distancia = -1, tolerancia
        for i in range(primero + 1, ultimo):
            px, py = puntos[i]
            if norma == 0.0:
                distancia = math.hypot(px - x1, py - y1)
            else:
                distancia = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / math.sqrt(norma)
            if distancia > peor_distancia:
                peor, peor_distancia = i, distancia
        if peor >= 0:
            conservar[peor] = True
            limites.append((primero, peor))
            limites.append((peor, ultimo))
    return [p for p, se_conserva in zip(puntos, conservar) if se_conserva]


class FuenteDatos:
    """Punto unico de acceso a los datos del simulador."""

    def __init__(self, carpeta: Path | None = None) -> None:
        self.carpeta = carpeta or CARPETA_DATOS
        self.aeropuertos: list[Aeropuerto] = []
        self.paises: list[Pais] = []
        self.avisos: list[str] = []
        self._indice_busqueda: list[tuple[str, str, str, str]] = []

    # --- carga ----------------------------------------------------------
    def cargar(self) -> "FuenteDatos":
        self._cargar_aeropuertos()
        self._cargar_paises()
        self._construir_indice()
        return self

    def _construir_indice(self) -> None:
        """Texto normalizado de cada aeropuerto, para que buscar sea inmediato."""
        self._indice_busqueda = [
            (normalizar(a.iata), normalizar(a.ciudad), normalizar(a.pais),
             normalizar(a.nombre))
            for a in self.aeropuertos
        ]

    def _cargar_aeropuertos(self) -> None:
        ruta = self.carpeta / "aeropuertos.csv"
        if not ruta.exists():
            self.avisos.append(
                f"No se encontro {ruta.name}. Ejecute: python herramientas/preparar_datos.py"
            )
            self.aeropuertos = [self._de_respaldo(fila) for fila in AEROPUERTOS_DE_RESPALDO]
            return
        with ruta.open(newline="", encoding="utf-8") as archivo:
            for registro in csv.DictReader(archivo):
                try:
                    self.aeropuertos.append(
                        Aeropuerto(
                            iata=registro["iata"],
                            icao=registro.get("icao", ""),
                            nombre=registro.get("nombre", ""),
                            ciudad=registro.get("ciudad", ""),
                            pais=registro.get("pais", ""),
                            lat=float(registro["lat"]),
                            lon=float(registro["lon"]),
                            elevacion_ft=int(registro.get("elevacion_ft") or 0),
                            tipo=registro.get("tipo", ""),
                        )
                    )
                except (KeyError, ValueError):
                    continue  # fila incompleta: se descarta sin romper la carga
        if not self.aeropuertos:
            self.avisos.append("aeropuertos.csv estaba vacio; se uso la lista minima.")
            self.aeropuertos = [self._de_respaldo(fila) for fila in AEROPUERTOS_DE_RESPALDO]

    @staticmethod
    def _de_respaldo(fila: tuple[str, str, str, str, float, float]) -> Aeropuerto:
        pais, iata, nombre, ciudad, lat, lon = fila
        return Aeropuerto(iata=iata, nombre=nombre, ciudad=ciudad, pais=pais, lat=lat, lon=lon)

    def _cargar_paises(self) -> None:
        ruta = self.carpeta / "paises.json"
        if not ruta.exists():
            self.avisos.append(
                f"No se encontro {ruta.name}; el mapa se dibujara sin contornos de pais."
            )
            return
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        self.paises = [
            Pais(nombre=f["nombre"], iso=f.get("iso", ""),
                 anillos=tuple(simplificar_anillo(anillo, TOLERANCIA_CONTORNOS)
                               for anillo in f["anillos"]))
            for f in datos.get("features", [])
        ]

    # --- consultas ------------------------------------------------------
    def por_iata(self, iata: str) -> Aeropuerto | None:
        return self.indice.get(iata.upper())

    @property
    def indice(self) -> dict[str, Aeropuerto]:
        if not hasattr(self, "_indice"):
            self._indice = {a.iata: a for a in self.aeropuertos}
        return self._indice

    def buscar(self, texto: str, limite: int = 12) -> list[Aeropuerto]:
        """Busqueda por codigo, ciudad, pais o nombre.

        El orden importa mas de lo que parece: al buscar «Quito», el aeropuerto
        de Quito debe salir antes que Iquitos, que solo contiene la cadena. Se
        ordena por relevancia (exacto, prefijo, alias,substring) y despues por
        tipo, no solo por tipo.

        Los indices normalizados se calculan una sola vez al cargar, porque
        normalizar 4.568 registros en cada pulsacion de teclado se notaria.
        """
        aguja = normalizar(texto)
        if not aguja:
            return []
        exactos = [a for a in self.aeropuertos if a.iata == aguja]
        if exactos:
            return exactos
        pais_alias = ALIAS_PAIS.get(aguja, "")
        ciudad_alias = ALIAS_CIUDAD.get(aguja, "")

        encontrados: list[tuple[tuple[int, int, str], Aeropuerto]] = []
        for aeropuerto, (iata, ciudad, pais, nombre) in zip(self.aeropuertos,
                                                            self._indice_busqueda):
            if aguja == iata or aguja == ciudad or aguja == pais or aguja == nombre:
                rango = 0
            elif iata.startswith(aguja) or ciudad.startswith(aguja) or pais.startswith(aguja):
                rango = 1
            elif (ciudad_alias and ciudad == ciudad_alias) or \
                 (pais_alias and pais.startswith(pais_alias)):
                rango = 2
            elif (ciudad_alias and ciudad_alias in ciudad) or \
                 (pais_alias and pais_alias in pais):
                rango = 3
            elif aguja in iata or aguja in ciudad or aguja in pais or aguja in nombre:
                rango = 4
            else:
                continue
            encontrados.append(
                ((rango, -(aeropuerto.tipo == "large_airport"), ciudad), aeropuerto))
        encontrados.sort(key=lambda par: par[0])
        return [aeropuerto for _, aeropuerto in encontrados[:limite]]

    def grandes(self) -> Iterator[Aeropuerto]:
        """Solo los aeropuertos grandes: reduce el ruido del mapa."""
        for aeropuerto in self.aeropuertos:
            if aeropuerto.tipo == "large_airport":
                yield aeropuerto


@lru_cache(maxsize=1)
def datos() -> FuenteDatos:
    """Punto de entrada cacheado: `datos().buscar("UIO")`."""
    return FuenteDatos().cargar()
