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

PLIEGO_PPT_EXTRACTION_PROMPT = """
Del siguiente texto del Pliego de Prescripciones Técnicas (PPT), 
extrae en formato JSON la siguiente información:
- entregables_clave: Lista de strings
- sla_acuerdos_nivel_servicio: Lista de requerimientos de SLA o métricas de calidad
- perfiles_profesionales: Lista de diccionarios con {{rol, experiencia_minima, titulacion}}
- certificaciones_tecnicas: Lista de certificaciones o estándares (ej. ISO 9001)
- tecnologias_obligatorias: Lista de software/hardware específico requerido
- lugar_ejecucion: String

Si alguna información no se encuentra, omite la clave o usa null.
Asegúrate de que la salida sea JSON válido.

Texto del PPT:
{ppt_text}
"""

PLIEGO_MATCH_PROMPT = """
Actúa como un analista de licitaciones. Tienes el perfil de una empresa (User Profile) 
y los requisitos extraídos de una licitación (PCAP y PPT).
Tu tarea es evaluar si la empresa cumple con los requisitos y calcular un "match_score" (0 a 100).
Si hay requisitos obligatorios que la empresa no cumple (ej. certificaciones que no tiene, 
facturación insuficiente para la solvencia, o no tiene los perfiles), añádelos a la lista de "blockers".

Responde ÚNICAMENTE en JSON con la siguiente estructura:
{{
  "match_score": 85,
  "blockers": ["Falta certificación ISO 27001", "La facturación de 500k no alcanza el mínimo de 1M requerido"],
  "razonamiento": "La empresa tiene los perfiles Java requeridos, pero..."
}}

Perfil de la empresa (JSON):
{profile_json}

Requisitos Administrativos PCAP (JSON):
{pcap_json}

Requisitos Técnicos PPT (JSON):
{ppt_json}
"""
