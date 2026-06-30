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
Actúa como un analista experto en contratación pública. Tienes el perfil de una empresa (User Profile) 
y los requisitos extraídos de una licitación (PCAP y PPT).
Tu tarea es evaluar si la empresa cumple con los requisitos obligatorios para presentarse a esta licitación.

Responde ÚNICAMENTE en JSON con la siguiente estructura exacta:
{{
  "veredicto": "YES" | "NO" | "MAYBE",
  "razonamiento_general": "Resumen de por qué la empresa es o no apta...",
  "requisitos_evaluados": [
    {{
      "requisito": "Certificación ISO 9001",
      "cumple": true | false,
      "razon": "La empresa indica tener ISO 9001 en su perfil."
    }},
    {{
      "requisito": "Perfil Senior Java (5 años)",
      "cumple": false,
      "razon": "No hay ningún empleado en el perfil que cumpla esta experiencia."
    }}
  ]
}}

Reglas del veredicto:
- YES: Cumple todos los requisitos críticos.
- NO: Falla en al menos un requisito técnico, financiero o certificación indispensable.
- MAYBE: Falta información en el perfil de la empresa para estar seguros, o hay requisitos ambiguos.

Perfil de la empresa (JSON):
{profile_json}

Requisitos Administrativos PCAP (JSON):
{pcap_json}

Requisitos Técnicos PPT (JSON):
{ppt_json}
"""
