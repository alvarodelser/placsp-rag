"""Themes for selecting the pilot's expedientes, by CPV only: urbanism, sustainability, mapping and
citizen participation.

Each theme is a curated list of CPV codes; a code stands for itself and everything under it
(71354000 "cartografía" takes 71354100 "cartografía digital"), less the codes in `exclude`; a code
written "=…" stands for itself only. An entry belongs to a theme when any CPV of the tender or of
its lots falls in it. Titles are not read: words gave insurance for a "Sociedad Urbanística" and
document custody for "sostenibilidad".
"""

THEMES = {
    "urbanismo": {
        "label": "Urbanismo y planeamiento",
        "cpv": ["71400000",   # planificación urbana y arquitectura paisajística
                "71410000",   # urbanismo
                "71420000",   # arquitectura paisajística
                "90712100"],  # planificación del desarrollo medioambiental urbano
        "exclude": ["71421000"],   # jardinería paisajística: mantenimiento, no planificación
    },
    "sostenibilidad": {
        "label": "Sostenibilidad y medio ambiente",
        "cpv": ["=90700000",  # servicios medioambientales: la raíz sola, no todo lo que cuelga de ella
                "90710000",   # gestión medioambiental: EIA, planificación, asesoramiento, auditoría, SIA
                "90720000", "90721000", "90721100", "90721800",   # protección del medio ambiente, paisaje, riesgos naturales
                "90731000",   # contaminación atmosférica: calidad del aire, CO2
                "90742000",   # contaminación acústica (mapas de ruido)
                "71313000",   # consultoría en ingeniería ambiental (ruido, impacto ambiental)
                "71314300"],  # consultoría en rendimiento energético
        "exclude": [],
    },
    "cartografia": {
        "label": "Cartografía y datos geográficos",
        "cpv": ["71354000",   # cartografía: digital, aérea, catastral, hidrográfica
                "71355000",   # agrimensura, fotogrametría, topografía catastral
                "71353000",   # mediciones topográficas de superficie
                "71351800",   # servicios topográficos
                "38221000",   # sistemas de información geográfica (SIG)
                "48326000",   # software cartográfico
                "90732500"],  # cartografía de contaminación del suelo
        "exclude": ["71354500"],   # investigación marítima
    },
    "participacion": {
        "label": "Participación ciudadana",
        "cpv": ["79315000",   # investigación social
                "79311200",   # dirección de estudios (encuestas)
                "98133000",   # servicios de asociaciones de carácter social
                "98133100"],  # mejoramiento cívico y apoyo a los servicios para la comunidad
        "exclude": [],
    },
}


def _stem(code: str) -> str:
    """The significant digits of a CPV code: 71354000 -> 71354 (its subtree); "=90700000" -> itself."""
    return code[1:] if code.startswith("=") else str(code).split("-")[0][:8].rstrip("0") or "0"


_MATCH = {k: ([_stem(c) for c in t["cpv"]], [_stem(c) for c in t["exclude"]]) for k, t in THEMES.items()}


def cpv_themes(code: str) -> list[str]:
    c = str(code).split("-")[0][:8]
    return [k for k, (inc, exc) in _MATCH.items()
            if any(c == p or (len(p) < 8 and c.startswith(p)) for p in inc) and not any(c.startswith(p) for p in exc)]


def themes_of(rec: dict) -> list[str]:
    """The themes a parsed feed entry belongs to, in THEMES order; [] if none."""
    tender = rec.get("tender") or {}
    cpvs = set(tender.get("cpv") or []) | {c for lot in rec.get("lots") or [] for c in lot.get("cpv") or []}
    found = {k for c in cpvs for k in cpv_themes(c)}
    return [k for k in THEMES if k in found]
