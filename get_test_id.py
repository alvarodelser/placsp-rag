import sys
import httpx
sys.path.append('src')
from placsp.config import load_config
cfg = load_config()

query = """
{
  Get {
    Placsp_licitaciones(limit: 10) {
      syndication_id
      expediente
      document_urls
    }
  }
}
"""
headers = {"Authorization": f"Bearer {cfg.weaviate_api_key}"} if cfg.weaviate_api_key else {}
r = httpx.post(f"{cfg.weaviate_url.rstrip('/')}/v1/graphql", json={'query': query}, headers=headers)
r.raise_for_status()

for lic in r.json()['data']['Get']['Placsp_licitaciones']:
    urls = lic.get('document_urls') or []
    for u in urls:
        if 'GetDocumentByIdServlet' in u:
            print(lic['syndication_id'])
            sys.exit(0)
print("None found")
