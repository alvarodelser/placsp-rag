import { shortOrg } from './labels.js'

describe('shortOrg', () => {
  it('drops the organ inside a council and abbreviates it', () => {
    expect(shortOrg('Alcaldía del Ayuntamiento de Coaña')).toBe('Ayto. Coaña')
    expect(shortOrg('Junta de Gobierno Local del Ayuntamiento de Madrid')).toBe('Ayto. Madrid')
    expect(shortOrg('Pleno del Ayuntamiento de Benabarre')).toBe('Ayto. Benabarre')
    expect(shortOrg('Diputación Provincial de Huesca')).toBe('Dip. Huesca')
  })
  it('drops the kind of entity', () => {
    expect(shortOrg('Organismo Autónomo Madrid Salud')).toBe('Madrid Salud')
    expect(shortOrg('Entidad Pública Empresarial ADIF')).toBe('ADIF')
  })
  it('drops legal forms and stops shouting', () => {
    expect(shortOrg('ESPUBLICO SERVICIOS PARA LA ADMINISTRACIÓN, S.A., SOCIEDAD UNIPERSONAL', 60)).toBe('Espublico Servicios para la Administración')
    expect(shortOrg('ESPUBLICO, SERVICIOS PARA LA ADMINISTRACIÓN, SA')).toBe('Espublico, Servicios…')
    expect(shortOrg('Construcciones Pérez S.L.U.')).toBe('Construcciones Pérez')
    expect(shortOrg('UTE TRAGSA TECNOLOGIAS')).toBe('UTE Tragsa Tecnologias')
  })
  it('cuts long names at a word', () => {
    expect(shortOrg('Consorcio de Transportes de la Comunidad de Madrid y su Área Metropolitana', 30)).toBe('Consorcio de Transportes…')
  })
})
