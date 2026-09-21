export function activeProfile(state) {
  return state?.profiles?.find(profile => profile.active) || state?.profiles?.[0] || null;
}

export function targetStack(jobDescription = '') {
  const text = jobDescription.toLowerCase();
  const stacks = [
    ['Azure', ['azure', 'adf', 'data factory', 'adls', 'synapse', 'fabric', 'event hubs']],
    ['GCP', ['gcp', 'google cloud', 'bigquery', 'gcs', 'dataflow', 'dataproc', 'pub/sub', 'composer']],
    ['AWS', ['aws', 'amazon web services', 's3', 'glue', 'redshift', 'kinesis', 'emr']],
  ];
  const scored = stacks.map(([name, terms]) => [name, terms.filter(term => text.includes(term)).length]);
  scored.sort((a, b) => b[1] - a[1]);
  return scored[0][1] ? scored[0][0] : 'JD-driven';
}

async function errorMessage(response) {
  const body = await response.json().catch(() => ({}));
  return body.detail || body.error || `Server error ${response.status}`;
}

export class InterviewPackClient {
  constructor(backend, token, fetcher = fetch) {
    this.backend = backend.replace(/\/$/, '');
    this.token = token;
    this.fetcher = fetcher;
  }

  async request(path, options = {}) {
    const response = await this.fetcher(this.backend + path, {
      ...options,
      headers: {'X-App-Token': this.token, ...(options.headers || {})},
    });
    if (!response.ok) throw new Error(await errorMessage(response));
    return response.json();
  }

  state() { return this.request('/api/state'); }

  create(name, jobDescription) {
    const body = new FormData();
    body.append('name', name);
    body.append('job_description', jobDescription);
    return this.request('/api/profiles', {method: 'POST', body});
  }

  activate(profileId) {
    return this.request(`/api/profiles/${encodeURIComponent(profileId)}/activate`, {method: 'POST'});
  }

  upload(profileId, kind, file) {
    const body = new FormData();
    body.append('kind', kind);
    body.append('file', file, file.name || 'interview-material.txt');
    return this.request(`/api/profiles/${encodeURIComponent(profileId)}/documents`, {method: 'POST', body});
  }

  addNotes(profileId, text) {
    const body = new FormData();
    body.append('kind', 'prep notes');
    body.append('file', new Blob([text], {type: 'text/plain'}), 'prep-notes.txt');
    return this.request(`/api/profiles/${encodeURIComponent(profileId)}/documents`, {method: 'POST', body});
  }
}
