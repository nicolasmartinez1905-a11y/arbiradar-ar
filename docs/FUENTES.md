# Fuentes públicas de cotizaciones

Documentación consultada el 26 de noviembre de 2026. Las integraciones consumen información pública de solo lectura.

| Fuente | Cobertura implementada | Política de consulta y vigencia |
| --- | --- | --- |
| [CriptoYa Argentina](https://docs.criptoya.com/argentina/) y [cotización general](https://docs.criptoya.com/argentina/operations/get-cotizacion-general.html) | USDT, USDC, DAI, BTC, ETH, XLM, XRP y SOL contra ARS. Cada respuesta identifica plataformas con datos disponibles para el par. Se preservan los precios base y totales provistos, por separado. | El proveedor declara actualización cada 60 s y hasta 120 solicitudes por minuto. Se usa el volumen predeterminado del proveedor, una pausa de un segundo entre pares y de 60 s entre lotes. Se considera vencido a partir de más de 90 s desde la publicación. |
| [DolarApi](https://dolarapi.com/docs/argentina/operations/get-dolares) | Referencias USD/ARS oficial, MEP (`bolsa`), CCL (`contadoconliqui`), cripto, mayorista, tarjeta y blue. | Pausa local de 60 s. Límite de antigüedad de 5 min. Las series que se renuevan más despacio mantienen visible su fecha original y pueden quedar marcadas como vencidas. Consultar las [condiciones de uso](https://dolarapi.com/docs/uso) antes de redistribuir datos. |
| [ComparaDólar](https://comparadolar.ar/openapi.json) | Pizarra USD/ARS por entidad a través de `/usd`. | Pausa local de 300 s. El campo `lastSeenAt` registra cuándo el agregador observó el valor. Se conserva separado de la hora de publicación, que queda como desconocida. Se respeta la marca de dato vencido de la fuente. |
| [Kraken Spot WebSocket](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ticker) | BTC, ETH, SOL, XRP, XLM, USDT y USDC contra USD, con mejor precio y cantidad de cada lado del libro cuando se informan. | Suscripción a cambios de punta del libro. Límite de antigüedad de 15 s. La caché conserva la fecha de origen aunque se sigan recibiendo señales de conexión. |

Las pausas de DolarApi y ComparaDólar son decisiones locales. La disponibilidad de una cotización depende del proveedor, del par, del volumen consultado y del momento. El dólar blue se conserva exclusivamente como referencia informativa. La cobertura cripto de los agregadores no acredita profundidad completa, condiciones de P2P, comisiones finales, disponibilidad de redes ni derecho a operar.

## Plataformas y fuentes adicionales

- **Bancos y billeteras.** [CriptoYa documenta una pizarra bancaria](https://docs.criptoya.com/argentina/operations/get-bancostodos.html) para BNA, Brubank, Galicia, Santander, BBVA, Macro y Provincia, entre otros. [ComparaDólar documenta su catálogo](https://comparadolar.ar/openapi.json), con ejemplos de Ualá, BNA, Provincia, BBVA y Brubank. La cobertura efectiva de cada entidad se lee de cada respuesta. Queda pendiente verificar APIs directas de cotización minorista de las nueve entidades. La [API de Mercado Pago](https://www.mercadopago.com.ar/developers/es/reference) y su integración internacional documentada no acreditan un feed público del precio minorista en la app. El [BCRA publica estadísticas cambiarias](https://www.bcra.gob.ar/apis-banco-central/) aptas como referencia, con frecuencia y finalidad distintas de una orden.
- **Exchanges argentinos.** [Ripio Trade](https://apidocs.ripiotrade.co/) y [Bitso](https://docs.bitso.com/bitso-api/docs/ticker) documentan tickers de mercado directos para evaluar en una futura integración. Para Buenbit, Ripio, Lemon, Belo, SatoshiTango, Bitso, Fiwind, LetsBit, Decrypto y Tienda Crypto se conservan los identificadores que CriptoYa devuelva efectivamente. Los endpoints directos de las demás plataformas quedan sin verificar.
- **Exchanges internacionales.** Junto con Kraken, se localizaron los catálogos de [Binance Spot](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams), [Bybit](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker), [Bitget](https://www.bitget.com/docs/uta/websocket/public/Tickers-Channel), [OKX](https://www.okx.com/docs-v5/en/) y [KuCoin](https://www.kucoin.com/docs-new/3470355w0). Se localizó el [portal de BingX](https://bingx-api.github.io/docs/), cuyo contrato spot quedó sin verificar. Cotizar un mercado spot internacional es independiente de poder comprar, vender o transferir para volver a ARS.

## Carga manual

Ejecuta `python -m backend.services.monitor --manual cotizaciones.json` con un archivo de hasta mil registros. Usa un objeto como el siguiente dentro de la lista. El ejemplo es ficticio. Sustituye su fecha por la fecha real de la cotización con zona horaria, y omite un lado si es desconocido.

```json
[
  {
    "mercado": "Entidad de ejemplo",
    "base": "USD",
    "contramoneda": "ARS",
    "compra_usuario": "1500.25",
    "venta_usuario": "1480.00",
    "publicada": "2026-01-01T12:00:00-03:00"
  }
]
```

El monitor lee una vez el archivo al arrancar. Registra estos datos como manuales, con vigencia local de cinco minutos. Guarda los archivos con datos de usuario fuera del repositorio.
