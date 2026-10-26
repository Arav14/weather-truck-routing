async function parse(res) {
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON error body */
  }
  if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
  return data;
}

export async function geocode(q, signal) {
  const data = await parse(await fetch(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }));
  return data.results;
}

export async function analyze(payload) {
  return parse(
    await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}
