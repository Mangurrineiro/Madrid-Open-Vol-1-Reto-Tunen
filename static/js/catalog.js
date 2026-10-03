// Catálogo: 6 capas agronómicas de la UI sobre los parámetros crudos del backend.

export const SOURCE_LABEL = { auto: 'Combined', derived: 'Combined', soilgrids: 'SoilGrids', lbeg: 'LBEG', buek200: 'BÜK200' };
export const SOURCE_NOTE = {
  soilgrids: 'ISRIC SoilGrids 250 m — global model',
  lbeg: 'LBEG data covers Lower Saxony only',
  buek200: 'BGR BÜK200 — national 1:200,000 soil map',
};

const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  texture: svg('<circle cx="7" cy="8" r="2.5"/><circle cx="16" cy="7" r="1.5"/><circle cx="12" cy="15" r="3.5"/><circle cx="19" cy="15" r="1"/><circle cx="5" cy="17" r="1.2"/>'),
  ph: svg('<path d="M12 3c3.5 4.2 6 7.6 6 10.6A6 6 0 0 1 6 13.6C6 10.6 8.5 7.2 12 3z"/><path d="M9.5 14.5a2.6 2.6 0 0 0 2.5 2.4"/>'),
  soc: svg('<path d="M5 19c0-8 5-13 14-14-1 9-6 14-14 14z"/><path d="M5 19l7-7"/>'),
  nfk: svg('<path d="M8 4c2.4 3 4 5.2 4 7.2a4 4 0 0 1-8 0C4 9.2 5.6 7 8 4z"/><path d="M17 10c1.8 2.2 3 3.9 3 5.4a3 3 0 0 1-6 0c0-1.5 1.2-3.2 3-5.4z"/>'),
  bodenzahl: svg('<path d="M12 3l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.8z"/>'),
  reliability: svg('<path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6z"/><path d="M8.8 12.2l2.2 2.2 4.3-4.6"/>'),
};

const has = (field, source, parameter) =>
  field.layers.some((l) => l.source === source && l.parameter === parameter && l.status === 'ok' && l.grid_url);

/**
 * Cada capa: resolve(field, sub, source) → {source, parameter, palette} para pintar ese campo.
 * uncertainty: parámetros de desacuerdo (spread) y σ del modelo (fallback), o null.
 */
export const LAYERS = [
  {
    id: 'texture', name: 'Texture', icon: ICON.texture, desc: 'Soil classes · clay, sand and silt',
    subs: [{ id: 'classes', label: 'Classes' }, { id: 'clay', label: 'Clay' }, { id: 'sand', label: 'Sand' }, { id: 'silt', label: 'Silt' }],
    sources: (sub) => (sub === 'classes' ? ['auto', 'lbeg', 'buek200'] : ['derived', 'soilgrids', 'buek200']),
    defaultSource: (sub) => (sub === 'classes' ? 'auto' : 'derived'),
    resolve(field, sub, src) {
      if (sub === 'classes') {
        const s = src === 'auto' ? (has(field, 'lbeg', 'bodenart_bs') ? 'lbeg' : 'buek200') : src;
        return s === 'lbeg' ? { source: 'lbeg', parameter: 'bodenart_bs', palette: 'bs' }
          : { source: 'buek200', parameter: 'ka5_class', palette: 'ka5' };
      }
      return { source: src, parameter: sub, palette: sub };
    },
    label: (sub) => (sub === 'classes' ? 'Texture class' : { clay: 'Clay', sand: 'Sand', silt: 'Silt' }[sub]),
    unit: (sub) => (sub === 'classes' ? '' : '%'),
    uncertainty: { spread: ['clay_disagreement', 'sand_disagreement', 'silt_disagreement'],
      sigma: ['clay_sigma', 'sand_sigma', 'silt_sigma'], unit: '%', noun: 'texture points' },
  },
  {
    id: 'ph', name: 'pH', icon: ICON.ph, desc: 'Soil acidity of the topsoil',
    sources: () => ['soilgrids', 'buek200'],
    defaultSource: () => 'soilgrids',
    resolve: (field, sub, src) => (src === 'buek200'
      ? { source: 'buek200', parameter: 'ph_cacl2', palette: 'ph' }
      : { source: 'soilgrids', parameter: 'ph_h2o', palette: 'ph' }),
    label: (sub, src) => (src === 'buek200' ? 'pH (CaCl₂, class estimate)' : 'pH (water)'),
    unit: () => '',
    uncertainty: null,
    uncertaintyNote: 'Not available: each source measures pH with a different method, so they are never combined.',
  },
  {
    id: 'soc', name: 'Organic carbon', icon: ICON.soc, desc: 'Soil organic carbon, 0–30 cm',
    sources: () => ['derived', 'soilgrids', 'buek200'],
    defaultSource: () => 'derived',
    resolve: (field, sub, src) => ({ source: src, parameter: 'soc', palette: 'soc' }),
    label: () => 'Organic carbon', unit: () => 'g/kg',
    uncertainty: { spread: ['soc_disagreement'], sigma: ['soc_sigma'], unit: 'g/kg', noun: 'g/kg' },
  },
  {
    id: 'nfk', name: 'Plant-available water', icon: ICON.nfk, desc: 'Water the roots can use (nFK)',
    sources: () => ['derived', 'soilgrids', 'lbeg'],
    defaultSource: () => 'derived',
    resolve: (field, sub, src) => ({ source: src, parameter: 'nfk', palette: 'nfk' }),
    label: () => 'Plant-available water', unit: () => 'mm/dm',
    uncertainty: { spread: ['nfk_disagreement'], sigma: ['nfk_sigma'], unit: 'mm/dm', noun: 'mm/dm' },
  },
  {
    id: 'bodenzahl', name: 'Soil quality', icon: ICON.bodenzahl, desc: 'Official Bodenzahl rating, 0–100',
    sources: () => ['lbeg'],
    defaultSource: () => 'lbeg',
    resolve: () => ({ source: 'lbeg', parameter: 'bodenzahl', palette: 'quality' }),
    label: () => 'Bodenzahl', unit: () => '',
    uncertainty: null,
    uncertaintyNote: 'Not available: single official rating from the German soil assessment.',
  },
  {
    id: 'reliability', name: 'Reliability', icon: ICON.reliability, desc: 'How much our data sources agree',
    sources: () => ['derived'],
    defaultSource: () => 'derived',
    resolve: () => ({ source: 'derived', parameter: 'sampling_priority', palette: 'reliability' }),
    label: () => 'Reliability index', unit: () => '',
    display: (p) => Math.round(100 * (1 - p)),
    uncertainty: null,
    panelNote: 'Reliability index (0-100): how much our data sources agree at each point',
  },
];

export const layerById = (id) => LAYERS.find((l) => l.id === id);

export function findLayer(field, source, parameter) {
  return field.layers.find((l) => l.source === source && l.parameter === parameter && l.status === 'ok' && l.grid_url) || null;
}

/** Fuentes de una capa con dato en al menos un campo. */
export function availableSources(layer, sub, fields) {
  return layer.sources(sub).filter((src) =>
    fields.some((f) => { const r = layer.resolve(f, sub, src); return !!findLayer(f, r.source, r.parameter); }));
}
