"""Page furniture, headings, section paths and section chunks (sections.py), and the layout pass."""
import pymupdf
import pytest

from placsp_pilot import sections as S
from placsp_pilot.textract import extract


def page(n: int, body: str) -> str:
    return (f"[Página {n}]\nAyuntamiento de Villaverde\nPLIEGO DE CLÁUSULAS ADMINISTRATIVAS\n{body}\n"
            f"Cód. Validación: 7XK{n}QZ{n * 3}PL | Verificación: https://villaverde.sedelectronica.es/\n"
            f"Página {n} de 4")


TEXT = "\n\n".join([
    page(1, "ÍNDICE\nCLÁUSULA 1. OBJETO ........................ 3\nCLÁUSULA 2. SOLVENCIA ..................... 5"),
    page(2, "CLÁUSULA 1. OBJETO\n" + "El objeto del contrato es el suministro de material. " * 40),
    page(3, "CLÁUSULA 2. SOLVENCIA\n2.1 Solvencia económica\nVolumen anual de negocios de 300.000 euros.\n"
            "2.2 Solvencia técnica\nTres trabajos similares en los últimos cinco años.\n"
            "| Lote | Importe |\n|---|---|\n| 1 | 10.000 |"),
    page(4, "ANEXO I. MODELO DE OFERTA\nD./Dña. ........ en nombre de ........"),
])


def test_furniture_is_detected_and_the_text_kept():
    st = S.Structure(TEXT)
    lines = [st.lines[i][1] for i in sorted(st.furniture)]
    assert "Ayuntamiento de Villaverde" in lines and "Página 3 de 4" in lines
    assert any(line.startswith("Cód. Validación") for line in lines)      # the code differs on each page
    assert not any(line.startswith("CLÁUSULA") or "Volumen" in line for line in lines)
    assert "Ayuntamiento de Villaverde" in TEXT                            # nothing removed
    body = S.without_furniture(TEXT, frozenset(st.furniture_keys))
    assert "Cód. Validación" not in body and "Página 2 de 4" not in body and "Volumen anual" in body


def test_headings_and_their_paths():
    st = S.Structure(TEXT)
    got = [(h["kind"], h["num"], h["level"], " › ".join(h["path"])) for h in st.headings]
    assert ("clause", "2", 1, "CLÁUSULA 2. SOLVENCIA") in got
    assert ("number", "2.1", 2, "CLÁUSULA 2. SOLVENCIA › 2.1 Solvencia económica") in got
    assert ("annex", "I", 1, "ANEXO I. MODELO DE OFERTA") in got
    # Not the index lines, not the furniture, not a table row.
    assert sum(1 for h in st.headings if h["num"] == "1") == 1
    assert not [h for h in st.headings if "Ayuntamiento" in h["label"] or h["label"].startswith("|")]
    off = TEXT.index("Tres trabajos")
    assert st.path_at(off) == ["CLÁUSULA 2. SOLVENCIA", "2.2 Solvencia técnica"]


def test_chunks_follow_sections_and_keep_every_word():
    chunks = S.chunk_sections(TEXT, 120)
    assert " ".join(c for c, _ in chunks).split() == TEXT.split()
    solv = next((c, p) for c, p in chunks if "Volumen anual" in c)
    # Either its own chunk, or the end of clause 1's with clause 2 named as opening inside it.
    assert "CLÁUSULA 2. SOLVENCIA" in solv[1]
    assert all(len(c.split()) <= 120 for c, _ in chunks)


def test_a_long_table_is_cut_at_rows():
    rows = "\n".join(f"| {i} | EMPRESA {i} SL | {i},00 | {90 - i},50 |" for i in range(60))
    text = "CLÁUSULA 1. VALORACIÓN\n| N.º | Licitador | Precio | Puntos |\n|---|---|---|---|\n" + rows
    chunks = S.chunk_sections(text, 100)
    assert " ".join(c for c, _ in chunks).split() == text.split()
    assert all(line.startswith("|") or line.startswith("CLÁUSULA") for c, _ in chunks for line in c.split("\n"))


def test_old_texts_keep_the_words_chunker():
    from placsp_pilot.nlpstages import split_words
    assert S.pieces(TEXT, 60, None) == split_words(TEXT, 60)
    assert S.pieces(TEXT, 60, "sections") == [c for c, _ in S.chunk_sections(TEXT, 60)]


@pytest.fixture(scope="module")
def pdf_bytes():
    doc = pymupdf.open()
    for n in range(1, 5):
        p = doc.new_page()
        p.insert_text((72, 40), "AYUNTAMIENTO DE VILLAVERDE - CONTRATACIÓN", fontsize=8)
        p.insert_text((72, 100), f"CLÁUSULA {n}. ASUNTO NÚMERO {n}", fontsize=14)
        y = 130
        for k in range(12):
            p.insert_text((72, y), f"Texto del apartado {n}.{k} sobre las condiciones del contrato y su ejecución.", fontsize=10)
            y += 16
        p.insert_text((250, 810), f"Página {n} de 4", fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def test_layout_pass_keeps_page_markers_and_marks_boxes(pdf_bytes):
    res = extract(pdf_bytes, "pdf", layout=True)
    assert res.status == "ok" and res.method == "pymupdf4llm"
    assert "[Página 1]" in res.text and "[Página 4]" in res.text
    plain = extract(pdf_bytes, "pdf")
    assert plain.method == "pymupdf" and plain.layout is None
    st = S.Structure(res.text, res.layout)
    furniture = " ".join(st.lines[i][1] for i in st.furniture)
    assert "Página 2 de 4" in furniture and "VILLAVERDE" in furniture
    assert sum(1 for h in st.headings if h["kind"] == "clause") == 4
    # Every span the layout pass gave lies inside the text.
    assert all(0 <= a <= b <= len(res.text) for v in res.layout.values() for a, b in v)
