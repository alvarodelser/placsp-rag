from dataclasses import dataclass
import datetime

@dataclass
class Feed:
    name: str
    category: str
    url: str
    year: int
    incremental: bool

_BASE = "https://contrataciondelsectorpublico.gob.es/sindicacion"
_CHANNELS = {
    "placsp_mayores":   ("sindicacion_643",  "licitacionesPerfilesContratanteCompleto3", 2012),
    "externos_mayores": ("sindicacion_1044", "PlataformasAgregadasSinMenores",           2016),
    "placsp_menores":   ("sindicacion_1143", "contratosMenoresPerfilesContratantes",     2018),
    "propios":          ("sindicacion_1383", "EMP_SectorPublico",                         2022),
}

def _build():
    feeds, current = [], datetime.date.today().year
    for cat, (sind, stem, start) in _CHANNELS.items():
        for year in range(start, current + 1):
            feeds.append(Feed(f"{cat}_{year}", cat,
                              f"{_BASE}/{sind}/{stem}_{year}.zip", year, year == current))
    return feeds

CATALOG = _build()

def live_head_url(category: str) -> str:
    sind, stem, _ = _CHANNELS[category]
    return f"{_BASE}/{sind}/{stem}.atom"
