export function processSignals(data, limit = null) {

  // shared filtering logic (ONE SOURCE OF TRUTH)
  let filtered = data.filter(x =>
    x.relVol > 1.2 && x.change1d > 0
  );

  // sort strongest first
  filtered.sort((a, b) => b.relVol - a.relVol);

  // optional limit (homepage uses 3, dashboard uses all)
  if (limit) {
    filtered = filtered.slice(0, limit);
  }

  return filtered;
}