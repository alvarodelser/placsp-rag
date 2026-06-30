PLIEGO_HTML_SUMMARY_PROMPT = """
Convierte la siguiente información estructurada extraída de un pliego de licitación
en un resumen claro y conciso en español, enfocado en lo que una empresa 
necesitaría saber rápidamente para decidir si presentarse. 
Formatea la salida en JSON con las claves: "resumen_general", "puntos_clave", "requisitos_criticos".

Datos:
{criteria_json}
"""

PLIEGO_PCAP_EXTRACTION_PROMPT = """
Del siguiente texto del Pliego de Cláusulas Administrativas Particulares (PCAP), 
extrae en formato JSON la siguiente información:
- penalidades: Lista de diccionarios con {{tipo, importe_o_porcentaje, descripcion}}
- forma_pago: Diccionario con {{plazo_dias, certificaciones}}
- modificaciones_contrato: Diccionario con {{permitidas (booleano), limite_porcentaje, condiciones}}
- subcontratacion: Diccionario con {{permitida (booleano), limite_porcentaje, condiciones}}
- seguros: Lista de diccionarios con {{tipo, importe_minimo}}
- cesion: Diccionario con {{permitida (booleano), condiciones}}
- resolucion: Diccionario con {{causas (lista), procedimiento}}

Si alguna información no se encuentra, omite la clave o usa null.
Asegúrate de que la salida sea JSON válido.

Texto del PCAP:
{ocr_text}
"""
