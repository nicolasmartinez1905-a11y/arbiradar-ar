from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

import httpx

from backend.adapters.market import cargar_json, comparadolar, criptoya, dolarapi, kraken_ticker
from backend.models.financial import OrigenDatos
from backend.models.market import Vigencia
from backend.services.collector import Cache, EstadoFuente, FuenteHTTP, Recolector, retry_after
from backend.services.monitor import fuentes, leer_manual

AHORA = datetime(2026, 1, 1, tzinfo=timezone.utc)
CRIPTOS = '{"exchange-prueba":{"ask":1500.1234567890123456789,"bid":1498,"totalAsk":1501,"time":1767225600}}'
DOLARES = '[{"moneda":"USD","casa":"blue","compra":1490,"venta":1500,"fechaActualizacion":"2026-01-01T00:00:00Z"}]'
TICKER = ('{"channel":"ticker","type":"snapshot","data":[{"symbol":"BTC/USD",'
          '"ask":89000.12,"bid":88999.99,"ask_qty":0.25,"timestamp":"2026-01-01T00:00:00Z"}]}')


class NormalizacionTest(TestCase):
    def test_criptoya_decimal_volumen_y_costos_ausentes(self):
        consulta = criptoya("USDT", volumen=Decimal("500"))
        self.assertEqual(consulta.url, "https://criptoya.com/api/USDT/ARS/500")
        lote = consulta.normalizar(cargar_json(CRIPTOS), AHORA)
        precio = lote.cotizaciones[0]
        self.assertEqual(precio.compra_usuario, Decimal("1500.1234567890123456789"))
        self.assertEqual(precio.compra_con_costos, Decimal("1501"))
        self.assertIsNone(precio.venta_con_costos)
        self.assertEqual(precio.volumen_consultado, Decimal("500"))
        self.assertEqual(precio.publicada, AHORA)
        self.assertTrue(precio.solo_referencia)

    def test_rechaza_respuestas_incompletas_y_par_invalido(self):
        for contenido in ("[]", "{}", '{"x":{"ask":true,"bid":0}}', '{"x":null}'):
            with self.subTest(contenido=contenido), self.assertRaises(ValueError):
                criptoya("BTC").normalizar(cargar_json(contenido), AHORA)
        with self.assertRaises(ValueError):
            criptoya("../USDT")

    def test_dolarapi_perspectiva_usuario_y_blue_informativo(self):
        precio = dolarapi().normalizar(cargar_json(DOLARES), AHORA).cotizaciones[0]
        self.assertEqual(precio.compra_usuario, Decimal("1500"))
        self.assertEqual(precio.venta_usuario, Decimal("1490"))
        self.assertEqual(precio.mercado, "blue")
        self.assertTrue(precio.solo_referencia)

    def test_comparadolar_no_confunde_observacion_con_publicacion(self):
        datos = '[{"slug":"banco-prueba","ask":1500,"bid":1490,"lastSeenAt":"2026-01-01T00:00:00Z"}]'
        precio = comparadolar().normalizar(cargar_json(datos), AHORA).cotizaciones[0]
        self.assertEqual(precio.observada_por_fuente, AHORA)
        self.assertIsNone(precio.antiguedad(AHORA))
        self.assertEqual(precio.vigencia(AHORA, timedelta(seconds=5)), Vigencia.DESCONOCIDA)

    def test_kraken_ignora_heartbeat_y_normaliza_ticker(self):
        self.assertIsNone(kraken_ticker({"channel": "heartbeat"}, AHORA))
        precio = kraken_ticker(cargar_json(TICKER), AHORA).cotizaciones[0]
        self.assertEqual(precio.cantidad_compra, Decimal("0.25"))
        self.assertEqual(precio.compra_usuario, Decimal("89000.12"))
        self.assertEqual((precio.base, precio.contramoneda), ("BTC", "USD"))

    def test_orden_temporal_cache(self):
        cache = Cache(estados={"DolarApi": EstadoFuente(conectada=True)},
                      vigencias={"DolarApi": timedelta(seconds=15)})
        precio = dolarapi().normalizar(cargar_json(DOLARES), AHORA).cotizaciones[0]
        previo = replace(precio, publicada=AHORA - timedelta(minutes=1))
        cache.guardar("DolarApi", (precio,), incremental=False)
        cache.guardar("DolarApi", (previo,), incremental=False)
        self.assertEqual(cache.instantanea(AHORA)[0]["precio"], precio)
        self.assertEqual(cache.instantanea(AHORA)[0]["vigencia"], Vigencia.ACTUAL)
        self.assertEqual(cache.instantanea(AHORA + timedelta(seconds=16))[0]["vigencia"], Vigencia.VENCIDA)

    def test_manual_con_origen_y_precision(self):
        with TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "manual.json"
            ruta.write_text('[{"mercado":"Banco de prueba","base":"USD","contramoneda":"ARS",'
                            '"compra_usuario":"1500.1234567890123456789","publicada":"2026-01-01T00:00:00Z"}]',
                            encoding="utf-8")
            precio, = leer_manual(ruta)
        self.assertEqual(precio.origen, OrigenDatos.MANUAL)
        self.assertEqual(precio.compra_usuario, Decimal("1500.1234567890123456789"))
        self.assertTrue(precio.solo_referencia)

    def test_intervalos_y_retry_after(self):
        cripto, dolar, compara = fuentes()
        self.assertEqual(len(cripto.consultas), 8)
        self.assertGreaterEqual(cripto.intervalo, 60)
        self.assertGreaterEqual(cripto.espacio, 1)
        self.assertGreaterEqual(dolar.intervalo, 60)
        self.assertGreaterEqual(compara.intervalo, 300)
        self.assertEqual(retry_after("Thu, 01 Jan 2026 00:02:00 GMT", AHORA), 120)
        self.assertEqual(retry_after("invalido", AHORA), 0)


class FinDePrueba(Exception):
    pass


class RecolectorTest(IsolatedAsyncioTestCase):
    async def test_429_backoff_circuit_breaker_y_recuperacion(self):
        secuencia = iter([
            httpx.Response(200, content=DOLARES), httpx.Response(429, headers={"Retry-After": "70"}),
            httpx.Response(503), httpx.Response(503), httpx.Response(200, content=DOLARES),
        ])
        eventos = []

        async def dormir(segundos):
            estado = recolector.cache.estados["DolarApi"]
            filas = recolector.cache.instantanea(AHORA)
            eventos.append((segundos, estado.conectada, estado.circuito_abierto, filas[0]["vigencia"]))
            if len(eventos) == 5:
                raise FinDePrueba

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(secuencia))) as cliente:
            recolector = Recolector(cliente, reloj=lambda: AHORA, dormir=dormir)
            with self.assertRaises(FinDePrueba):
                await recolector.seguir_http(FuenteHTTP("DolarApi", (dolarapi(),), 5, 1, timedelta(seconds=15)))
        self.assertEqual(eventos, [
            (5, True, False, Vigencia.ACTUAL), (70, False, False, Vigencia.DESCONECTADA),
            (10, False, False, Vigencia.DESCONECTADA), (120, False, True, Vigencia.DESCONECTADA),
            (5, True, False, Vigencia.ACTUAL),
        ])

    async def test_lote_parcial_conserva_pares_validos(self):
        secuencia = iter([httpx.Response(200, content="{}"), httpx.Response(200, content=CRIPTOS)])
        pausas = []

        async def dormir(segundos):
            pausas.append(segundos)
            if len(pausas) == 2:
                raise FinDePrueba

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(secuencia))) as cliente:
            recolector = Recolector(cliente, reloj=lambda: AHORA, dormir=dormir)
            fuente = FuenteHTTP("CriptoYa", (criptoya("USDC"), criptoya("USDT")), 60, 1, timedelta(seconds=90))
            with self.assertRaises(FinDePrueba):
                await recolector.seguir_http(fuente)
        self.assertEqual(pausas, [1, 60])
        self.assertEqual(recolector.cache.estados["CriptoYa"].filas_invalidas, 1)
        self.assertEqual(recolector.cache.instantanea(AHORA)[0]["precio"].base, "USDT")

    async def test_reconexion_websocket_y_cache_por_sesion(self):
        conexiones = []
        estados = []

        class Socket:
            def __init__(self, simbolo):
                self.mensajes = iter(['{"channel":"heartbeat"}', TICKER.replace("BTC/USD", simbolo)])

            async def send(self, datos):
                self.suscripcion = cargar_json(datos)
                conexiones.append(self.suscripcion["params"]["event_trigger"])

            async def recv(self):
                try:
                    return next(self.mensajes)
                except StopIteration:
                    raise OSError("Dato de prueba") from None

        @asynccontextmanager
        async def conectar(*args, **kwargs):
            yield Socket("BTC/USD" if not conexiones else "ETH/USD")

        async def dormir(segundos):
            filas = recolector.cache.instantanea(AHORA)
            estados.append((segundos, filas[0]["vigencia"], [f["precio"].base for f in filas]))
            if len(estados) == 2:
                raise FinDePrueba

        async with httpx.AsyncClient() as cliente:
            recolector = Recolector(cliente, reloj=lambda: AHORA, dormir=dormir, conectar=conectar)
            with self.assertRaises(FinDePrueba):
                await recolector.seguir_kraken()
        self.assertEqual(conexiones, ["bbo", "bbo"])
        self.assertEqual(estados, [(5, Vigencia.DESCONECTADA, ["BTC"]),
                                   (5, Vigencia.DESCONECTADA, ["ETH"])])
