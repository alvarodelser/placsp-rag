RISK_ANALYSIS_PROMPT = """
Basado en las cláusulas legales extraídas del Pliego de Cláusulas Administrativas (PCAP)
y las condiciones de la licitación, realiza un Análisis de Riesgos Financieros y Legales
para una empresa licitadora.

Identifica y devuelve en formato JSON válido con las siguientes claves:
- "banderas_rojas": Lista de condiciones inusualmente estrictas o atípicas (ej. penalidades > 10%, plazos de pago muy largos, garantías excesivas).
- "riesgos_ejecucion": Lista de riesgos operativos derivados del contrato.
- "nivel_riesgo_global": Un string ("Bajo", "Medio", "Alto").
- "justificacion": Breve texto justificando el nivel.

Datos extraídos del PCAP:
{pcap_json}

Datos extraídos de las condiciones (HTML):
{criteria_json}
"""

SCORING_STRATEGY_PROMPT = """
Basado en los criterios de adjudicación extraídos del pliego de la licitación,
analiza la estructura de puntuación y propón la estrategia óptima para la empresa licitadora.

Devuelve en formato JSON válido con las siguientes claves:
- "tipo_licitacion": String ("Orientada a Precio", "Orientada a Calidad", "Mixta").
- "criterio_decisivo": El criterio que probablemente decidirá el ganador.
- "estrategia_recomendada": Un párrafo explicando dónde la empresa debe enfocar sus esfuerzos en la oferta.
- "riesgo_baja_temeraria": Evaluación de si hay un alto riesgo de bajas desproporcionadas por el peso del precio.

Criterios de Adjudicación:
{criteria_json}
"""

EXECUTIVE_SUMMARY_PROMPT = """
Eres un analista experto en contratación pública. Analiza la siguiente licitación y 
emite una recomendación ejecutiva de "Bid / No-Bid" (Presentarse o No Presentarse)
para la gerencia de una empresa constructora/servicios.

Devuelve en formato JSON válido con las siguientes claves:
- "recomendacion": "BID" o "NO-BID" o "REQUIERE_ANALISIS_PROPIO".
- "razones_a_favor": Lista de 2-3 puntos fuertes de esta licitación.
- "razones_en_contra": Lista de 2-3 riesgos principales.
- "veredicto_ejecutivo": Un párrafo corto de conclusión.

Criterios:
{criteria_json}

Riesgos (PCAP):
{pcap_json}
"""
