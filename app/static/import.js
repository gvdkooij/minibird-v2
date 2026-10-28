const form = document.getElementById('import-form');
if (form) {
  const status = document.getElementById('upload-status');
  const progress = document.getElementById('upload-progress');
  const button = form.querySelector('button[type=submit]');
  const input = form.querySelector('input[type=file]');
  let csrf = form.querySelector('input[name=csrf]').value;
  async function freshToken() {
    const response = await fetch('/imports/token', {credentials: 'same-origin', cache: 'no-store'});
    if (!response.ok || response.redirected) throw new Error('Je sessie is verlopen. Log opnieuw in en kies het bestand nogmaals.');
    return (await response.json()).csrf;
  }
  async function api(url, options = {}, refreshed = false) {
    let response;
    try {
      response = await fetch(url, {...options, credentials: 'same-origin', headers: {'X-CSRF-Token': csrf, ...options.headers}});
    } catch {
      throw new Error('De verbinding is onderbroken. Kies Bestand controleren om opnieuw te proberen.');
    }
    if (response.redirected && new URL(response.url).pathname === '/login') {
      throw new Error('Je sessie is verlopen. Log opnieuw in en kies het bestand nogmaals.');
    }
    if (!response.ok) {
      if (response.status === 413) throw new Error('De uploadlimiet is bereikt. Kies een bestand van maximaal 50 MB.');
      if (response.status === 403 && !refreshed) {
        csrf = await freshToken();
        return api(url, options, true);
      }
      if (response.status === 403) throw new Error('Je beveiligingscode kon niet worden vernieuwd. Vernieuw de pagina.');
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      throw new Error(html.querySelector('[role=alert]')?.textContent || `Upload mislukt (${response.status}). Probeer opnieuw.`);
    }
    return response.json();
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const file = input.files[0];
    if (!file) return;
    if (file.size > 50 * 1024 * 1024) {
      status.textContent = 'Dit bestand is te groot. Kies een export van maximaal 50 MB.';
      return;
    }
    button.disabled = true;
    input.disabled = true;
    form.setAttribute('aria-busy', 'true');
    progress.hidden = false;
    progress.value = 0;
    progress.max = file.size;
    status.textContent = 'Upload voorbereiden…';
    let upload;
    try {
      csrf = await freshToken();
      upload = await api('/imports/uploads/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filename: file.name, size: file.size})});
      for (let offset = 0, part = 0; offset < file.size; offset += upload.chunk_size, part++) {
        const result = await api(`/imports/uploads/${upload.id}/chunks/${part}`, {method: 'PUT', headers: {'Content-Type': 'application/octet-stream'}, body: file.slice(offset, offset + upload.chunk_size)});
        progress.value = result.received;
        status.textContent = `Bestand uploaden: ${Math.round(result.received / file.size * 100)}%`;
      }
      status.textContent = 'Upload ontvangen. Contacten en documenten controleren…';
      const result = await api(`/imports/uploads/${upload.id}/complete`, {method: 'POST'});
      window.location.assign(result.preview);
    } catch (error) {
      status.textContent = error.message;
      if (upload) {
        try { await api(`/imports/uploads/${upload.id}`, {method: 'DELETE'}); } catch { /* Expired uploads are also removed server-side. */ }
      }
      button.disabled = false;
      input.disabled = false;
      form.removeAttribute('aria-busy');
    }
  });
}

for (const action of document.querySelectorAll('form[data-current-session]')) {
  action.addEventListener('submit', async event => {
    event.preventDefault();
    const button = action.querySelector('button');
    const status = document.getElementById('confirm-status');
    button.disabled = true;
    try {
      const response = await fetch('/imports/token', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || response.redirected) throw new Error('Je sessie is verlopen. Log opnieuw in om verder te gaan.');
      action.querySelector('input[name=csrf]').value = (await response.json()).csrf;
      HTMLFormElement.prototype.submit.call(action);
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
}
