import re
from dataclasses import dataclass, field
from bs4 import BeautifulSoup
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

@dataclass
class PliegoCriteria:
    # Award criteria
    criterios_adjudicacion: List[Dict[str, any]] = field(default_factory=list)
    
    # Guarantees
    garantia_definitiva_pct: Optional[float] = None
    garantia_complementaria_pct: Optional[float] = None
    garantia_plazo_dias: Optional[int] = None
    
    # Solvency & classification
    clasificacion_empresarial: List[str] = field(default_factory=list)
    condiciones_admision: List[str] = field(default_factory=list)
    motivos_exclusion: List[str] = field(default_factory=list)
    num_empleados_min: Optional[int] = None
    
    # Execution
    plazo_ejecucion: Optional[str] = None
    condiciones_especiales: List[str] = field(default_factory=list)
    subcontratacion: Optional[str] = None
    
    # Offer preparation
    sobres: List[Dict[str, str]] = field(default_factory=list)
    plazo_validez_oferta: Optional[str] = None
    
    # Bid opening
    apertura_fecha: Optional[str] = None
    apertura_lugar: Optional[str] = None
    
    # Nested PDF links for Tier 2/3
    pdf_links: List[Dict[str, str]] = field(default_factory=list)
    
    # Descriptive
    descripcion_procedimiento: Optional[str] = None
    directiva_aplicacion: Optional[str] = None
    regulacion_armonizada: bool = False

class PliegoHTMLParser:
    def __init__(self, html_content: str):
        self.soup = BeautifulSoup(html_content, 'html.parser')
        
    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        return " ".join(text.replace("\n", " ").replace("\r", " ").split()).strip()

    def _extract_number(self, text: str) -> Optional[float]:
        if not text:
            return None
        match = re.search(r'([\d,.]+)', text)
        if match:
            # Handle Spanish number format (e.g., 5,5 or 1.000,50)
            num_str = match.group(1).replace('.', '').replace(',', '.')
            try:
                return float(num_str)
            except ValueError:
                return None
        return None

    def parse(self) -> PliegoCriteria:
        criteria = PliegoCriteria()
        
        # 1. Regulacion Armonizada
        armonizada = self.soup.find('h3', string=lambda t: t and 'Contrato Sujeto a regulación armonizada' in t)
        if armonizada and armonizada.find('div', class_='noremarca'):
            val = self._clean_text(armonizada.find('div', class_='noremarca').text).lower()
            criteria.regulacion_armonizada = val == 'si' or val == 'sí'

        # 2. Directiva de aplicacion
        dir_span = self.soup.find('span', string=lambda t: t and 'Directiva de aplicación' in t)
        if dir_span and dir_span.find_next_sibling('div', class_='noremarca'):
            criteria.directiva_aplicacion = self._clean_text(dir_span.find_next_sibling('div', class_='noremarca').text)

        # 3. Plazo de Ejecucion
        plazo_span = self.soup.find('span', string=lambda t: t and 'Plazo de Ejecución' in t)
        if plazo_span:
            # The structure might be li > span then ul > li > div.noremarca
            parent_li = plazo_span.parent
            next_ul = parent_li.find_next_sibling('ul')
            if next_ul:
                plazo_div = next_ul.find('div', class_='noremarca')
                if plazo_div:
                    criteria.plazo_ejecucion = self._clean_text(plazo_div.text)

        # 4. PDF Links
        for a_tag in self.soup.find_all('a', href=True):
            href = a_tag['href']
            if 'GetDocumentByIdServlet' in href or 'drive.google.com' in href:
                text = self._clean_text(a_tag.text)
                if text:
                    criteria.pdf_links.append({"nombre": text, "url": href})

        # 5. Descripcion del procedimiento
        desc_span = self.soup.find('span', string=lambda t: t and 'Descripción del procedimiento' in t)
        if desc_span and desc_span.parent:
            parent_li = desc_span.parent
            desc_text = parent_li.next_sibling
            if desc_text and isinstance(desc_text, str):
                criteria.descripcion_procedimiento = self._clean_text(desc_text)
            elif parent_li.parent:
               # sometimes it's directly in the parent as text
               text = self._clean_text(parent_li.parent.text)
               text = text.replace("Descripción del procedimiento", "").strip()
               if text:
                   criteria.descripcion_procedimiento = text

        # 6. Condiciones Especiales
        cond_esp_span = self.soup.find('span', string=lambda t: t and 'Condiciones especiales de ejecución de Contrato' in t)
        if cond_esp_span and cond_esp_span.parent:
            next_ul = cond_esp_span.find_next_sibling('ul')
            if not next_ul and cond_esp_span.parent.find('ul'):
                 next_ul = cond_esp_span.parent.find('ul')
            if next_ul:
                for div in next_ul.find_all('div', class_='noremarca'):
                     criteria.condiciones_especiales.append(self._clean_text(div.text))
        
        # 7. Garantias
        garantia_def = self.soup.find('h4', string=lambda t: t and 'Garantía Requerida' in t and 'Definitiva' in t)
        if garantia_def:
            ul = garantia_def.find_next_sibling('ul')
            if ul:
                pct_span = ul.find('span', string=lambda t: t and 'Porcentaje' in t)
                if pct_span and pct_span.find_next_sibling('div', class_='noremarca'):
                    criteria.garantia_definitiva_pct = self._extract_number(pct_span.find_next_sibling('div', class_='noremarca').text)
                
                plazo_h5 = ul.find('h5', string=lambda t: t and 'Plazo de constitución' in t)
                if plazo_h5:
                    plazo_ul = plazo_h5.find_next_sibling('ul')
                    if plazo_ul and plazo_ul.find('div', class_='noremarca'):
                         val = self._extract_number(plazo_ul.find('div', class_='noremarca').text)
                         if val:
                             criteria.garantia_plazo_dias = int(val)

        garantia_comp = self.soup.find('h4', string=lambda t: t and 'Garantía Requerida' in t and 'Complementaria' in t)
        if garantia_comp:
            ul = garantia_comp.find_next_sibling('ul')
            if ul:
                pct_span = ul.find('span', string=lambda t: t and 'Porcentaje' in t)
                if pct_span and pct_span.find_next_sibling('div', class_='noremarca'):
                    criteria.garantia_complementaria_pct = self._extract_number(pct_span.find_next_sibling('div', class_='noremarca').text)

        # 8. Requisitos de participacion
        req_part = self.soup.find('h4', string=lambda t: t and 'Requisitos de participación' in t)
        if req_part:
            ul = req_part.find_next_sibling('ul')
            if ul:
                emp_span = ul.find('span', string=lambda t: t and 'Número de Empleados' in t)
                if emp_span and emp_span.find_next_sibling('div', class_='noremarca'):
                    criteria.num_empleados_min = int(self._extract_number(emp_span.find_next_sibling('div', class_='noremarca').text) or 0)
                
                clasif_h5 = ul.find('h5', string=lambda t: t and 'Clasificación empresarial' in t)
                if clasif_h5:
                    clasif_ul = clasif_h5.find_next_sibling('ul')
                    if clasif_ul:
                         for div in clasif_ul.find_all('div', class_='noremarca'):
                             criteria.clasificacion_empresarial.append(self._clean_text(div.text))
                             
                cond_adm_h5 = ul.find('h5', string=lambda t: t and 'Condiciones de admisión' in t)
                if cond_adm_h5:
                    cond_ul = cond_adm_h5.find_next_sibling('ul')
                    if cond_ul:
                         for li in cond_ul.find_all('li', recursive=False):
                             criteria.condiciones_admision.append(self._clean_text(li.text))
                             
                mot_excl_h5 = ul.find('h5', string=lambda t: t and 'Motivos de exclusión' in t)
                if mot_excl_h5:
                    mot_ul = mot_excl_h5.find_next_sibling('ul')
                    if mot_ul:
                         for div in mot_ul.find_all('div', class_='noremarca'):
                             text = self._clean_text(div.text)
                             if text and text != '-':
                                 criteria.motivos_exclusion.append(text)

        # 9. Preparacion de oferta (sobres)
        for prep_h4 in self.soup.find_all('h4', string=lambda t: t and 'Preparación de oferta' in t):
            ul = prep_h4.find_next_sibling('ul')
            if ul:
                sobre = {}
                sobre_span = ul.find('span', string=lambda t: t and 'Sobre' in t)
                if sobre_span and sobre_span.find_next_sibling('div', class_='noremarca'):
                    sobre['descripcion'] = self._clean_text(sobre_span.find_next_sibling('div', class_='noremarca').text)
                
                tipo_span = ul.find('span', string=lambda t: t and 'Tipo de Oferta' in t)
                if tipo_span and tipo_span.find_next_sibling('div', class_='noremarca'):
                    sobre['tipo'] = self._clean_text(tipo_span.find_next_sibling('div', class_='noremarca').text)
                
                if sobre:
                    criteria.sobres.append(sobre)

        # 10. Criterios de Adjudicacion
        crit_h5 = self.soup.find('h5', string=lambda t: t and 'Criterios de Adjudicación' in t)
        if crit_h5:
            # Find all nested uls that represent a criterion
            # Structure is typically: ul > ul > li > div.noremarca (Name) + ul > li > div.noremarca (subtipo/ponderacion)
            parent_ul = crit_h5.find_next_sibling('ul')
            if parent_ul:
                 # Find all direct child ULs (each is a criterion)
                 for crit_ul in parent_ul.find_all('ul', recursive=False):
                     c = {}
                     # The name is usually in the first li > div.noremarca
                     first_li = crit_ul.find('li')
                     if first_li and first_li.find('div', class_='noremarca'):
                         c['nombre'] = self._clean_text(first_li.find('div', class_='noremarca').text)
                     
                     # Subtipo and Ponderacion are in a nested ul
                     nested_ul = crit_ul.find('ul')
                     if nested_ul:
                         for li in nested_ul.find_all('li'):
                             if li.find('span', string=lambda t: t and 'Subtipo Criterio' in t):
                                 # We need to extract the text after the span, which is just in the li
                                 full_text = self._clean_text(li.text)
                                 c['subtipo'] = full_text.split(':')[-1].strip() if ':' in full_text else full_text
                             elif li.find('span', string=lambda t: t and 'Ponderación' in t):
                                 full_text = self._clean_text(li.text)
                                 val = self._extract_number(full_text)
                                 if val is not None:
                                     c['ponderacion'] = val
                     if c:
                         criteria.criterios_adjudicacion.append(c)

        # 11. Plazo Validez Oferta
        validez_h4 = self.soup.find('h4', string=lambda t: t and 'Plazo de Validez de la Oferta' in t)
        if validez_h4:
            ul = validez_h4.find_next_sibling('ul')
            if ul and ul.find('div', class_='noremarca'):
                criteria.plazo_validez_oferta = self._clean_text(ul.find('div', class_='noremarca').text)

        # 12. Apertura
        apertura_h3 = self.soup.find('h3', string=lambda t: t and 'Apertura de Ofertas' in t)
        if apertura_h3:
            # Let's find the specific date/time
            for div in self.soup.find_all('div', class_='noremarca'):
                 text = self._clean_text(div.text)
                 if 'El día' in text and 'a las' in text:
                     criteria.apertura_fecha = text
            
            lugar_h5 = self.soup.find('h5', string=lambda t: t and 'Lugar' in t)
            if lugar_h5:
                ul = lugar_h5.find_next_sibling('ul')
                if ul and ul.find('div', class_='noremarca'):
                     criteria.apertura_lugar = self._clean_text(ul.find('div', class_='noremarca').text)

        return criteria
