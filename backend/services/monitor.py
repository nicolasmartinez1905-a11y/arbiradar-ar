"""Punto de entrada del proceso de monitoreo, sin servidor HTTP público."""
import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal

import httpx

from backend.adapters.market import comparadolar, criptoya, dolarapi
from backend.models.financial import OrigenDatos
from backend.models.market import PrecioMercado
from backend.services.collector import FuenteHTTP, Recolector, utc

ACTIVOS = ("USDT", "USDC", "DAI", "BTC", "ETH", "XLM", "XRP", "SOL")


def fuentes() -> tuple[FuenteHTTP, ...]:
    return (
        FuenteHTTP("CriptoYa", tuple(criptoya(activo) for activo in ACTIVOS), 60, 1, timedelta(seconds=90)),
        FuenteHTTP("DolarApi", (dolarapi(),), 60, 1, timedelta(minutes=5)),
        FuenteHTTP("ComparaDólar", (comparadolar(),), 300, 1, timedelta(minutes=5)),
    )


def leer_manual(ruta) -> tuple[PrecioMercado, ...]:
    with open(ruta, encoding="utf-8") as archivo:
        datos = json.load(archivo, parse_float=Decimal)
    if not isinstance(datos, list) or len(datos) > 1000:
        raise ValueError("Se requiere una lista de hasta 1000 cotizaciones manuales")
    recibida = utc()
    precios = []
    for fila in datos:
        def importe(campo):
            valor = fila.get(campo)
            if valor is None:
                return None
            if type(valor) not in (str, int, Decimal):
                raise ValueError("Importe manual inválido")
            return Decimal(valor)

        precios.append(PrecioMercado(
            "Carga manual", fila["mercado"], fila["base"], fila["contramoneda"], recibida,
            importe("compra_usuario"), importe("venta_usuario"),
            publicada=datetime.fromisoformat(fila["publicada"]), origen=OrigenDatos.MANUAL,
        ))
    return tuple(precios)


async def ejecutar(*, manual: tuple[PrecioMercado, ...] = (), websocket: bool = True) -> None:
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as cliente:
        recolector = Recolector(cliente)
        async with asyncio.TaskGroup() as tareas:
            for fuente in fuentes():
                tareas.create_task(recolector.seguir_http(fuente))
            if websocket:
                tareas.create_task(recolector.seguir_kraken())
            while True:
                await asyncio.sleep(5)
                ahora = utc()
                filas = recolector.cache.instantanea(ahora)
                for precio in manual:
                    filas.append({
                        "precio": precio,
                        "antiguedad_segundos": precio.antiguedad(ahora).total_seconds(),
                        "vigencia": precio.vigencia(ahora, timedelta(minutes=5)),
                    })
                print(json.dumps({
                    "hora": ahora,
                    "fuentes": {nombre: asdict(estado) for nombre, estado in recolector.cache.estados.items()},
                    "cotizaciones": [{**fila, "precio": asdict(fila["precio"])} for fila in filas],
                }, default=str, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitoreo público de cotizaciones de ArbiRadar AR")
    parser.add_argument("--manual", metavar="ARCHIVO", help="Cotizaciones manuales en JSON")
    parser.add_argument("--sin-websocket", action="store_true", help="Desactiva Kraken")
    args = parser.parse_args()
    try:
        manual = leer_manual(args.manual) if args.manual else ()
    except (OSError, KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        parser.error("Archivo manual inválido. Revisa el esquema documentado.")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(ejecutar(manual=manual, websocket=not args.sin_websocket))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
