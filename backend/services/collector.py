"""Recolector permanente, con caché acotada al último dato de cada mercado."""
import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import AsyncContextManager

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from backend.adapters.market import (
    KRAKEN_PARES, KRAKEN_URL, Consulta, Lote, cargar_json, kraken_ticker,
)
from backend.models.market import PrecioMercado

LOG = logging.getLogger(__name__)
MAX_BYTES = 2_000_000


def utc() -> datetime:
    return datetime.now(timezone.utc)


def retry_after(valor: str | None, ahora: datetime) -> float:
    if not valor:
        return 0
    if valor.isascii() and valor.isdecimal():
        try:
            return float(int(valor))
        except (OverflowError, ValueError):
            return float("inf")
    try:
        fecha = parsedate_to_datetime(valor)
        return max(0, (fecha - ahora).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0


class RespuestaHTTP(Exception):
    def __init__(self, codigo: int, espera: float) -> None:
        super().__init__(f"HTTP {codigo}")
        self.espera = espera


@dataclass(frozen=True)
class FuenteHTTP:
    nombre: str
    consultas: tuple[Consulta, ...]
    intervalo: float
    espacio: float
    vigencia: timedelta

    def __post_init__(self) -> None:
        if not self.consultas or self.intervalo < 5 or self.espacio <= 0:
            raise ValueError("Configura al menos una consulta y respeta la frecuencia mínima")


@dataclass
class EstadoFuente:
    conectada: bool = False
    ultimo_exito: datetime | None = None
    latencia_ms: int | None = None
    fallos: int = 0
    filas_invalidas: int = 0
    error: str | None = None
    reintento_en: datetime | None = None
    circuito_abierto: bool = False


@dataclass
class Cache:
    _datos: dict[str, dict[tuple[str, str, str], PrecioMercado]] = field(default_factory=dict)
    estados: dict[str, EstadoFuente] = field(default_factory=dict)
    vigencias: dict[str, timedelta] = field(default_factory=dict)

    def guardar(self, fuente: str, precios: tuple[PrecioMercado, ...], *, incremental: bool) -> None:
        previos = self._datos.get(fuente, {})
        siguientes = dict(previos) if incremental else {}
        for precio in precios:
            clave = (precio.mercado, precio.base, precio.contramoneda)
            previo = siguientes.get(clave) or previos.get(clave)
            if previo is not None and previo.publicada is not None and (
                precio.publicada is not None and previo.publicada > precio.publicada
            ):
                siguientes[clave] = previo
            else:
                siguientes[clave] = precio
        self._datos[fuente] = siguientes

    def reiniciar(self, fuente: str) -> None:
        self._datos.pop(fuente, None)

    def instantanea(self, ahora: datetime) -> list[dict]:
        filas = []
        for fuente, precios in self._datos.items():
            estado = self.estados[fuente]
            for precio in precios.values():
                edad = precio.antiguedad(ahora)
                filas.append({
                    "precio": precio,
                    "antiguedad_segundos": edad.total_seconds() if edad is not None else None,
                    "vigencia": precio.vigencia(ahora, self.vigencias[fuente], conectada=estado.conectada),
                })
        return filas


class Recolector:
    def __init__(
        self,
        cliente: httpx.AsyncClient,
        *,
        reloj: Callable[[], datetime] = utc,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        conectar: Callable[..., AsyncContextManager] = connect,
    ) -> None:
        self.cliente = cliente
        self.reloj = reloj
        self.dormir = dormir
        self.conectar = conectar
        self.cache = Cache()

    async def _consultar(self, consulta: Consulta) -> Lote:
        async with asyncio.timeout(10), self.cliente.stream("GET", consulta.url) as respuesta:
            if respuesta.status_code != 200:
                raise RespuestaHTTP(
                    respuesta.status_code,
                    retry_after(respuesta.headers.get("Retry-After"), self.reloj()),
                )
            datos = bytearray()
            async for bloque in respuesta.aiter_bytes(chunk_size=65536):
                datos.extend(bloque)
                if len(datos) > MAX_BYTES:
                    raise ValueError("Respuesta demasiado grande")
            return consulta.normalizar(cargar_json(bytes(datos)), self.reloj())

    async def _lote_http(self, fuente: FuenteHTTP, estado: EstadoFuente) -> None:
        precios = []
        invalidas = 0
        latencia = 0
        for indice, consulta in enumerate(fuente.consultas):
            if indice:
                await self.dormir(fuente.espacio)
            inicio = time.monotonic()
            try:
                lote = await self._consultar(consulta)
            except ValueError:
                invalidas += 1
            else:
                precios.extend(lote.cotizaciones)
                invalidas += lote.filas_invalidas
            finally:
                latencia += round((time.monotonic() - inicio) * 1000)
        if not precios:
            raise ValueError("El lote no contiene precios utilizables")
        self.cache.guardar(fuente.nombre, tuple(precios), incremental=False)
        self._exito(estado, latencia, invalidas)

    def _exito(self, estado: EstadoFuente, latencia: int | None, invalidas: int) -> None:
        estado.conectada = True
        estado.ultimo_exito = self.reloj()
        estado.latencia_ms = latencia
        estado.filas_invalidas = invalidas
        estado.fallos = 0
        estado.error = None
        estado.reintento_en = None
        estado.circuito_abierto = False

    async def _reintentar(self, nombre: str, estado: EstadoFuente, error: Exception, piso: float) -> None:
        estado.conectada = False
        estado.fallos += 1
        estado.circuito_abierto = estado.fallos >= 3
        if isinstance(error, RespuestaHTTP):
            estado.error = str(error)
            espera_servidor = error.espera
        elif isinstance(error, ValueError):
            estado.error = "Respuesta o suscripción inválida"
            espera_servidor = 0
        else:
            estado.error = "Conexión interrumpida o tiempo de espera agotado"
            espera_servidor = 0
        pausa = max(piso, espera_servidor, min(300, 5 * 2 ** min(estado.fallos - 1, 6)))
        if estado.circuito_abierto:
            pausa = max(pausa, 120)
        try:
            estado.reintento_en = self.reloj() + timedelta(seconds=pausa)
        except OverflowError:
            estado.reintento_en = None
        LOG.warning("%s · %s · próximo intento en %s s", nombre, estado.error, pausa)
        await self.dormir(pausa)
        estado.reintento_en = None

    async def seguir_http(self, fuente: FuenteHTTP) -> None:
        estado = self.cache.estados[fuente.nombre] = EstadoFuente()
        self.cache.vigencias[fuente.nombre] = fuente.vigencia
        while True:
            try:
                await self._lote_http(fuente, estado)
            except (RespuestaHTTP, httpx.HTTPError, TimeoutError, ValueError) as error:
                await self._reintentar(fuente.nombre, estado, error, fuente.intervalo)
            else:
                await self.dormir(fuente.intervalo)

    async def _sesion_kraken(self, estado: EstadoFuente) -> None:
        async with self.conectar(KRAKEN_URL, open_timeout=10, ping_interval=20, max_size=MAX_BYTES) as socket:
            await socket.send(json.dumps({
                "method": "subscribe",
                "params": {"channel": "ticker", "symbol": KRAKEN_PARES, "event_trigger": "bbo"},
            }))
            primer_ticker = True
            while True:
                datos = await asyncio.wait_for(socket.recv(), timeout=30)
                recibida = self.reloj()
                lote = kraken_ticker(cargar_json(datos), recibida)
                if lote is None:
                    continue
                if primer_ticker:
                    self.cache.reiniciar("Kraken")
                    primer_ticker = False
                self.cache.guardar("Kraken", lote.cotizaciones, incremental=True)
                edades = [(recibida - precio.publicada).total_seconds()
                          for precio in lote.cotizaciones if precio.publicada is not None]
                latencia = round(max(edades) * 1000) if edades else None
                self._exito(estado, latencia, lote.filas_invalidas)

    async def seguir_kraken(self) -> None:
        estado = self.cache.estados["Kraken"] = EstadoFuente()
        self.cache.vigencias["Kraken"] = timedelta(seconds=15)
        while True:
            try:
                await self._sesion_kraken(estado)
            except (WebSocketException, OSError, TimeoutError, ValueError) as error:
                await self._reintentar("Kraken", estado, error, 5)
