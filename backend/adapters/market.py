"""Adaptadores públicos de solo lectura. Los importes son precios unitarios."""
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from backend.models.market import PrecioMercado


def cargar_json(datos: str | bytes) -> Any:
    return json.loads(datos, parse_float=Decimal)


def positivo(valor: object) -> Decimal | None:
    if type(valor) not in (Decimal, int):
        return None
    numero = Decimal(valor)
    return numero if numero.is_finite() and numero > 0 else None


def fecha_iso(valor: object) -> datetime | None:
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ValueError("Fecha ISO inválida")
    fecha = datetime.fromisoformat(valor)
    if fecha.utcoffset() is None:
        raise ValueError("Fecha sin zona horaria")
    return fecha


def fecha_unix(valor: object) -> datetime | None:
    segundos = positivo(valor)
    if segundos is None:
        return None
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        microseconds=int(segundos * 1_000_000),
    )


@dataclass(frozen=True)
class Lote:
    cotizaciones: tuple[PrecioMercado, ...]
    filas_invalidas: int


def normalizar_filas(filas, convertir: Callable) -> Lote:
    cotizaciones = []
    invalidas = 0
    for clave, fila in filas:
        try:
            if not isinstance(fila, dict):
                raise ValueError("Fila inválida")
            cotizaciones.append(convertir(clave, fila))
        except (ValueError, TypeError, KeyError, OverflowError):
            invalidas += 1
    if not cotizaciones:
        raise ValueError("La fuente no devolvió cotizaciones utilizables")
    return Lote(tuple(cotizaciones), invalidas)


@dataclass(frozen=True)
class Consulta:
    url: str
    normalizar: Callable[[Any, datetime], Lote]


def criptoya(base: str, moneda: str = "ARS", volumen: Decimal | None = None) -> Consulta:
    activos = {"USDT", "USDC", "DAI", "BTC", "ETH", "XLM", "XRP", "SOL"}
    if base not in activos or moneda not in {"ARS", "USD"}:
        raise ValueError("Par fuera del catálogo inicial de CriptoYa")
    if volumen is not None and (type(volumen) is not Decimal or positivo(volumen) is None
                                or not Decimal("0.00000001") <= volumen <= Decimal("1000000000")):
        raise ValueError("Volumen inválido")
    url = f"https://criptoya.com/api/{base}/{moneda}"
    if volumen is not None:
        url += f"/{volumen:f}"

    def normalizar(datos: Any, recibida: datetime) -> Lote:
        if not isinstance(datos, dict):
            raise ValueError("Se esperaba un objeto por exchange")

        def convertir(exchange, fila):
            return PrecioMercado(
                "CriptoYa", exchange, base, moneda, recibida,
                positivo(fila.get("ask")), positivo(fila.get("bid")),
                publicada=fecha_unix(fila.get("time")),
                compra_con_costos=positivo(fila.get("totalAsk")),
                venta_con_costos=positivo(fila.get("totalBid")),
                volumen_consultado=volumen,
            )

        return normalizar_filas(datos.items(), convertir)

    return Consulta(url, normalizar)


def dolarapi() -> Consulta:
    def normalizar(datos: Any, recibida: datetime) -> Lote:
        if not isinstance(datos, list):
            raise ValueError("Se esperaba un listado de mercados")

        def convertir(_, fila):
            if fila.get("moneda") != "USD" or not isinstance(fila.get("casa"), str):
                raise ValueError("Mercado de dólar inválido")
            return PrecioMercado(
                "DolarApi", fila["casa"], "USD", "ARS", recibida,
                positivo(fila.get("venta")), positivo(fila.get("compra")),
                publicada=fecha_iso(fila.get("fechaActualizacion")),
            )

        return normalizar_filas(enumerate(datos), convertir)

    return Consulta("https://dolarapi.com/v1/dolares", normalizar)


def comparadolar() -> Consulta:
    def normalizar(datos: Any, recibida: datetime) -> Lote:
        if not isinstance(datos, list):
            raise ValueError("Se esperaba un listado de proveedores")

        def convertir(_, fila):
            if not isinstance(fila.get("slug"), str):
                raise ValueError("Proveedor sin identificador")
            return PrecioMercado(
                "ComparaDólar", fila["slug"], "USD", "ARS", recibida,
                positivo(fila.get("ask")), positivo(fila.get("bid")),
                observada_por_fuente=fecha_iso(fila.get("lastSeenAt")),
                vencida_en_fuente=fila.get("stale") is True,
            )

        return normalizar_filas(enumerate(datos), convertir)

    return Consulta("https://api.comparadolar.ar/usd", normalizar)


KRAKEN_URL = "wss://ws.kraken.com/v2"
KRAKEN_PARES = ("BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "XLM/USD", "USDT/USD", "USDC/USD")


def kraken_ticker(datos: Any, recibida: datetime) -> Lote | None:
    if not isinstance(datos, dict):
        raise ValueError("Mensaje WebSocket inválido")
    if datos.get("method") == "subscribe" and datos.get("success") is False:
        raise ValueError("Kraken rechazó una suscripción")
    if datos.get("channel") != "ticker":
        return None
    if datos.get("type") not in {"snapshot", "update"} or not isinstance(datos.get("data"), list):
        raise ValueError("Ticker incompleto")

    def convertir(_, fila):
        par = fila["symbol"]
        if par not in KRAKEN_PARES:
            raise ValueError("Par ajeno a la suscripción")
        base, moneda = par.split("/")
        return PrecioMercado(
            "Kraken", "spot", base, moneda, recibida,
            positivo(fila.get("ask")), positivo(fila.get("bid")),
            publicada=fecha_iso(fila.get("timestamp")),
            cantidad_compra=positivo(fila.get("ask_qty")),
            cantidad_venta=positivo(fila.get("bid_qty")),
        )

    return normalizar_filas(enumerate(datos["data"]), convertir)
