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
y los requisitos de una licitación procedentes de tres fuentes:
1. Requisitos estructurados de la plataforma oficial PLACSP (la fuente MÁS FIABLE: clasificación
   empresarial exigida, condiciones de admisión, motivos de exclusión, nº mínimo de empleados,
   garantías y criterios de adjudicación).
2. Requisitos administrativos extraídos del PCAP (PDF).
3. Requisitos técnicos extraídos del PPT (PDF).

Tu tarea es evaluar si la empresa cumple con los requisitos OBLIGATORIOS para presentarse.

Reglas de uso de las fuentes:
- Da prioridad a los requisitos estructurados de la plataforma cuando existan.
- IMPORTANTE: un campo estructurado vacío o ausente significa "no consta en la plataforma",
  NO significa "no se exige". En ese caso, apóyate en el PCAP/PPT para deducir el requisito.
- No inventes requisitos que no aparezcan en ninguna de las tres fuentes.

Responde ÚNICAMENTE en JSON con la siguiente estructura exacta:
{{
  "veredicto": "YES" | "NO" | "MAYBE",
  "razonamiento_general": "Resumen de por qué la empresa es o no apta...",
  "requisitos_evaluados": [
    {{
      "requisito": "Clasificación empresarial Grupo M Subgrupo 4",
      "fuente": "plataforma" | "pcap" | "ppt",
      "cumple": true | false,
      "razon": "La empresa indica disponer de esa clasificación en su perfil."
    }}
  ]
}}

Reglas del veredicto:
- YES: Cumple todos los requisitos críticos.
- NO: Falla en al menos un requisito técnico, financiero, de clasificación o certificación indispensable.
- MAYBE: Falta información en el perfil de la empresa para estar seguros, o hay requisitos ambiguos.

Perfil de la empresa (JSON):
{profile_json}

Requisitos estructurados de la plataforma PLACSP (JSON):
{criteria_json}

Requisitos Administrativos PCAP (JSON):
{pcap_json}

Requisitos Técnicos PPT (JSON):
{ppt_json}
"""
