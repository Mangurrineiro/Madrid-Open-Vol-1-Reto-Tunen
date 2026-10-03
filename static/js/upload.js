// Zona de arrastrar y soltar + selector de archivo (.geojson / .json).
// La validación y la pantalla de carga se completan en la etapa 1.4.

export function initDropzone(zone, input, onFile) {
  const accept = (f) => f && /\.(geo)?json$/i.test(f.name);
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => { if (input.files[0]) onFile(input.files[0]); input.value = ''; });
  for (const ev of ['dragenter', 'dragover']) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); });
  }
  for (const ev of ['dragleave', 'drop']) {
    zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('over'); });
  }
  zone.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files[0];
    if (!accept(f)) { setZoneMessage(zone, 'Please drop a .geojson or .json file.', true); return; }
    onFile(f);
  });
}

export function setZoneMessage(zone, text, isError = false) {
  const m = zone.querySelector('.drop-msg');
  if (!m) return;
  m.textContent = text;
  m.classList.toggle('error', isError);
}
