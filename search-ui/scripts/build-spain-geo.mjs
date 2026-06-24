// search-ui/scripts/build-spain-geo.mjs
// Fetch Eurostat Nuts2json, filter to Spain (ES*), convert to GeoJSON,
// and write compact files baked into the app. Geometry rarely changes — run on demand.
import { writeFileSync, mkdirSync } from 'node:fs'
import { feature } from 'topojson-client'

const BASE = 'https://raw.githubusercontent.com/eurostat/Nuts2json/master/pub/v2/2024/4326/10M'
const OUT = new URL('../src/geo/', import.meta.url)
mkdirSync(OUT, { recursive: true })

async function build(level, outName) {
  const res = await fetch(`${BASE}/${level}.json`)
  if (!res.ok) throw new Error(`HTTP ${res.status} fetching ${BASE}/${level}.json`)
  const data = await res.json()

  // Robust: handle both TopoJSON and already-GeoJSON responses
  let features
  if (data.type === 'Topology') {
    const objName = Object.keys(data.objects)[0]
    const fc = feature(data, data.objects[objName])
    features = fc.features
  } else {
    // Already GeoJSON FeatureCollection
    features = data.features
  }

  const esFeatures = features
    .filter((f) => {
      const id = f.id ?? f.properties?.id ?? f.properties?.NUTS_ID ?? ''
      return String(id).startsWith('ES')
    })
    .map((f) => {
      const id = f.id ?? f.properties?.id ?? f.properties?.NUTS_ID
      const name =
        f.properties?.na ??
        f.properties?.name ??
        f.properties?.NAME_LATN ??
        ''
      return {
        type: 'Feature',
        id,
        properties: { name },
        geometry: f.geometry,
      }
    })

  const fc = { type: 'FeatureCollection', features: esFeatures }
  writeFileSync(new URL(outName, OUT), JSON.stringify(fc))
  console.log(`${outName}: ${esFeatures.length} ES features`)
}

await build('2', 'spain-nuts2.json')
await build('3', 'spain-nuts3.json')
