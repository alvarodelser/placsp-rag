import sys
from pprint import pprint
sys.path.append('src')
from placsp.pliego_html_parser import PliegoHTMLParser

# Read the HTML content (skip markdown header lines)
with open('/Users/alvarodelser/.gemini/antigravity/brain/4f3cea2d-c2e0-4a30-9ec2-76d323918450/.system_generated/steps/103/content.md', 'r') as f:
    lines = f.readlines()
    html = "".join(lines[8:]) # Skip the first 8 lines which are metadata/markdown

parser = PliegoHTMLParser(html)
criteria = parser.parse()

pprint(criteria.__dict__)
