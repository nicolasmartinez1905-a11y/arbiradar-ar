from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from unittest import TestCase

from backend.engine.financial import evaluar_circuito
from backend.models.financial import (
    Costos, Cotizacion, Estado, Evidencia, Nodo, Operacion, OrigenDatos, Paso,
)

AHORA = datetime(2026, 1, 1, tzinfo=timezone.utc)
ARS = Nodo("Banco de prueba", "ARS")
USD = Nodo("Banco de prueba", "USD")
USDT = Nodo("Exchange de prueba", "USDT", 6)
USD_EXCHANGE = Nodo("Exchange de prueba", "USD")
COTIZACION = Cotizacion("Fixture de prueba", OrigenDatos.MANUAL, AHORA)
EVIDENCIA = Evidencia(True, True, True, True, "Fixture operativa", "Fixture normativa", AHORA)
SIN_COSTO = Costos(D("0"), D("0"), D("0"), D("0"))


def paso(origen, destino, operacion, tasa):
    return Paso(
        origen, destino, operacion, D(tasa), COTIZACION, SIN_COSTO,
        D("0"), D("10000000"), D("10000000"), 3, evidencia=EVIDENCIA,
    )


RUTA = (
    paso(ARS, USD, Operacion.COMPRA, "0.001"),
    paso(USD, USD_EXCHANGE, Operacion.TRANSFERENCIA_BANCARIA, "1"),
    paso(USD_EXCHANGE, USDT, Operacion.CONVERSION, "0.99"),
    paso(USDT, USD_EXCHANGE, Operacion.CONVERSION, "1"),
    paso(USD_EXCHANGE, USD, Operacion.TRANSFERENCIA_BANCARIA, "1"),
    paso(USD, ARS, Operacion.VENTA, "1100"),
)


class MotorFinancieroTest(TestCase):
    def evaluar(self, ruta=RUTA, **opciones):
        return evaluar_circuito(ARS, ruta, ahora=AHORA, **opciones)

    def test_conversiones_y_rentabilidad(self):
        resultado = self.evaluar()
        self.assertEqual(resultado.estado, Estado.VALIDADA)
        self.assertEqual(resultado.capital_final, D("1089000"))
        self.assertEqual(resultado.rentabilidad, D("8.9"))
        self.assertEqual(resultado.margen_seguridad_pp, D("7.9"))
        self.assertEqual(resultado.segundos_estimados, 18)

    def test_comisiones_slippage_impuestos_y_redondeo(self):
        venta = replace(RUTA[-1], costos=Costos(D("13.333"), D("0.01"), D("0.02"), D("0.03")))
        resultado = self.evaluar((*RUTA[:-1], venta))
        self.assertEqual(resultado.capital_final, D("1024838.03"))
        self.assertEqual(resultado.costos_totales, D("64161.97"))
        self.assertEqual(resultado.ganancia_bruta, D("89000"))
        self.assertEqual(resultado.ganancia_neta, D("24838.03"))

    def test_insumos_monetarios_invalidos(self):
        for valor in (1.5, D("NaN"), D("Infinity"), D("-1"), D("1.001")):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self.evaluar(capital=valor)

    def test_liquidez_y_limites(self):
        for cambio in ({"liquidez": D("999999")}, {"maximo": D("999999")}, {"minimo": D("1000001")}):
            with self.subTest(cambio=cambio):
                resultado = self.evaluar((replace(RUTA[0], **cambio), *RUTA[1:]))
                self.assertEqual(resultado.estado, Estado.DESCARTADA)

    def test_cotizacion_desactualizada_aunque_se_reciba_ahora(self):
        antigua = replace(COTIZACION, publicada=AHORA - timedelta(seconds=16))
        resultado = self.evaluar((replace(RUTA[0], cotizacion=antigua), *RUTA[1:]))
        self.assertEqual(resultado.estado, Estado.EXPIRADA)

    def test_fuente_desconectada_o_fecha_futura(self):
        for dato in (replace(COTIZACION, disponible=False),
                     replace(COTIZACION, recibida=AHORA + timedelta(seconds=1))):
            with self.subTest(dato=dato):
                resultado = self.evaluar((replace(RUTA[0], cotizacion=dato), *RUTA[1:]))
                self.assertEqual(resultado.estado, Estado.PENDIENTE)
                self.assertFalse(resultado.apta_para_revision_manual)

    def test_costo_desconocido_no_se_trata_como_cero(self):
        incompleto = replace(SIN_COSTO, fijo=None)
        resultado = self.evaluar((replace(RUTA[0], costos=incompleto), *RUTA[1:]))
        self.assertEqual(resultado.estado, Estado.TEORICA)
        self.assertIsNone(resultado.capital_final)
        self.assertIsNone(resultado.rentabilidad)
        self.assertFalse(resultado.apta_para_revision_manual)

    def test_faltan_datos_relevantes(self):
        for cambio in (
            {"minimo": None}, {"maximo": None}, {"liquidez": None}, {"segundos": None},
            {"evidencia": Evidencia()}, {"evidencia": replace(EVIDENCIA, fuente_normativa="")},
            {"evidencia": replace(EVIDENCIA, revisada=AHORA - timedelta(days=2))},
        ):
            with self.subTest(cambio=cambio):
                resultado = self.evaluar((replace(RUTA[0], **cambio), *RUTA[1:]))
                self.assertEqual(resultado.estado, Estado.PENDIENTE)
                self.assertFalse(resultado.apta_para_revision_manual)

    def test_red_incompatible_o_desconocida(self):
        for red, esperado in (("B", Estado.DESCARTADA), (None, Estado.PENDIENTE)):
            transferencia = replace(
                RUTA[1], operacion=Operacion.TRANSFERENCIA_BLOCKCHAIN,
                red_origen="A", red_destino=red,
            )
            self.assertEqual(self.evaluar((RUTA[0], transferencia, *RUTA[2:])).estado, esperado)

    def test_circuitos_imposibles(self):
        for ruta in ((), RUTA[:-1], (RUTA[0], *RUTA[2:])):
            self.assertEqual(self.evaluar(ruta).estado, Estado.DESCARTADA)
        self.assertEqual(self.evaluar(max_operaciones=5).estado, Estado.DESCARTADA)

    def test_restricciones_confirmadas(self):
        for campo in ("operacion_permitida", "pagos_compatibles", "titularidad_compatible", "normativa_compatible"):
            evidencia = replace(EVIDENCIA, **{campo: False})
            resultado = self.evaluar((replace(RUTA[0], evidencia=evidencia), *RUTA[1:]))
            self.assertEqual(resultado.estado, Estado.DESCARTADA)

    def test_rentabilidad_negativa_y_umbral(self):
        venta = replace(RUTA[-1], tasa=D("990"))
        resultado = self.evaluar((*RUTA[:-1], venta))
        self.assertLess(resultado.rentabilidad, D("0"))
        self.assertEqual(resultado.estado, Estado.DESCARTADA)
        self.assertEqual(self.evaluar(minimo_porcentual=D("9")).estado, Estado.DESCARTADA)
        self.assertEqual(self.evaluar(minimo_porcentual=D("8.9")).estado, Estado.VALIDADA)

    def test_simulacion_no_valida_una_oportunidad(self):
        simulada = replace(COTIZACION, origen=OrigenDatos.SIMULADO)
        resultado = self.evaluar((replace(RUTA[0], cotizacion=simulada), *RUTA[1:]))
        self.assertEqual(resultado.estado, Estado.SIMULADA)
        self.assertFalse(resultado.apta_para_revision_manual)

    def test_restriccion_posterior_con_importe_desconocido(self):
        inicial = replace(RUTA[0], costos=Costos())
        final = replace(RUTA[-1], evidencia=replace(EVIDENCIA, normativa_compatible=False))
        resultado = self.evaluar((inicial, *RUTA[1:-1], final))
        self.assertEqual(resultado.estado, Estado.DESCARTADA)
        self.assertIsNone(resultado.pasos[-1].entrada)

    def test_costos_que_agotan_el_importe(self):
        final = replace(RUTA[-1], costos=replace(SIN_COSTO, fijo=D("1090000")))
        resultado = self.evaluar((*RUTA[:-1], final))
        self.assertEqual(resultado.estado, Estado.DESCARTADA)
        self.assertIsNone(resultado.capital_final)
