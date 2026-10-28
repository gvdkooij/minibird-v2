// Keep imports independent of proxy handling of a separate token endpoint.
// The authenticated import page already contains a CSRF token for this session.
async function importResponseError(response, fallback) {
  const location = new URL(response.url, window.location.href);
  if (location.origin !== window.location.origin) {
    return new Error('GitHub heeft de verbinding naar een andere pagina omgeleid. Open MiniBird opnieuw via de browserlink van je Codespace.');
  }
  if (response.status === 401) {
    if (response.headers.get('X-MiniBird-Response') !== '1') {
      return new Error('De upload wordt geweigerd vóór een herkenbaar antwoord van MiniBird (MB-UPSTREAM-401). Dit bevestigt niet dat je MiniBird-sessie verlopen is. Je bestand blijft geselecteerd.');
    }
    const body = await response.json().catch(() => ({}));
    const codes = ['MB-COOKIE-MISSING', 'MB-COOKIE-INVALID', 'MB-AUTH-REQUIRED'];
    const code = codes.includes(body.code) ? body.code : 'MB-AUTH-REQUIRED';
    if (code === 'MB-COOKIE-MISSING') return new Error('De browser stuurde de MiniBird-sessiecookie niet mee (MB-COOKIE-MISSING). Je bestand blijft geselecteerd.');
    if (code === 'MB-COOKIE-INVALID') return new Error('De MiniBird-sessiecookie wordt niet geaccepteerd (MB-COOKIE-INVALID). Je bestand blijft geselecteerd.');
    return new Error('Je bent niet meer ingelogd in MiniBird (MB-AUTH-REQUIRED). Je bestand blijft geselecteerd.');
  }
  if (location.pathname === '/login') {
    return new Error('De aanvraag is naar de inlogpagina omgeleid (MB-LOGIN-REDIRECT). Je bestand blijft geselecteerd.');
  }
  let message;
  if ((response.headers.get('content-type') || '').includes('application/json')) {
    const body = await response.json().catch(() => ({}));
    if (typeof body.detail === 'string') message = body.detail;
  } else {
    const html = new DOMParser().parseFromString(await response.text(), 'text/html');
    message = html.querySelector('[role=alert]')?.textContent;
  }
  return new Error(`${message || fallback} (HTTP ${response.status}). Je gekozen bestand blijft geselecteerd.`);
}

async function currentImportCsrf() {
  let response;
  try {
    response = await fetch('/imports', {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'text/html'}});
  } catch {
    throw new Error('De importpagina is niet bereikbaar. Probeer opnieuw zodra de verbinding is hersteld.');
  }
  const location = new URL(response.url, window.location.href);
  if (!response.ok || location.origin !== window.location.origin || location.pathname === '/login') {
    throw await importResponseError(response, 'De importpagina kan niet worden gecontroleerd');
  }
  const html = new DOMParser().parseFromString(await response.text(), 'text/html');
  const token = html.querySelector('#import-form input[name=csrf]')?.value;
  if (!token) throw new Error('De server leverde geen geldige importpagina. Dit is geen melding dat je sessie verlopen is.');
  return token;
}

const form = document.getElementById('import-form');
if (form) {
  const status = document.getElementById('upload-status');
  const progress = document.getElementById('upload-progress');
  const button = form.querySelector('button[type=submit]');
  const input = form.querySelector('input[type=file]');
  let csrf = form.querySelector('input[name=csrf]').value;
  async function api(url, options = {}, refreshed = false) {
    let response;
    try {
      response = await fetch(url, {...options, credentials: 'same-origin', headers: {'Accept': 'application/json', 'X-CSRF-Token': csrf, ...options.headers}});
    } catch {
      throw new Error('De verbinding is onderbroken. Kies Bestand controleren om opnieuw te proberen.');
    }
    const location = new URL(response.url, window.location.href);
    if (location.origin !== window.location.origin || location.pathname === '/login' || response.status === 401) {
      throw await importResponseError(response, 'Import niet bereikbaar');
    }
    if (!response.ok) {
      if (response.status === 413) throw new Error('De uploadlimiet is bereikt. Kies een bestand van maximaal 50 MB.');
      if (response.status === 403 && !refreshed) {
        csrf = await currentImportCsrf();
        return api(url, options, true);
      }
      throw await importResponseError(response, 'De importaanvraag is geweigerd');
    }
    if (!(response.headers.get('content-type') || '').includes('application/json')) {
      throw new Error('De upload kreeg een onverwachte pagina terug. Dit is geen bevestiging dat je sessie verlopen is. Je bestand blijft geselecteerd.');
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
        try { await api(`/imports/uploads/${upload.id}`, {method: 'DELETE'}); } catch { /* Stale uploads are also removed server-side. */ }
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
      action.querySelector('input[name=csrf]').value = await currentImportCsrf();
      HTMLFormElement.prototype.submit.call(action);
    } catch (error) {
      status.textContent = error.message;
      button.disabled = false;
    }
  });
}
