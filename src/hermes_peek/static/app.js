const root = document.querySelector('#preview-app');
const previewId = root?.dataset.previewId;
const tg = window.Telegram?.WebApp;

function setState(name, message = '') {
  root.className = `state ${name}`;
  root.innerHTML = message ? `<p>${message}</p>` : '';
}

async function request(url, options = {}) {
  const response = await fetch(url, {credentials: 'same-origin', ...options});
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  if (response.status === 204) return null;
  return response.json();
}

async function authenticate() {
  if (!tg?.initData) return;
  await fetch(`/api/auth/telegram`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({preview_id: previewId, init_data: Telegram.WebApp.initData}),
  }).then(async response => {
    if (!response.ok) throw new Error(`${response.status}: authentication failed`);
  });
}

async function showFile(file) {
  const panel = document.createElement('section');
  panel.className = 'file-panel';
  const heading = document.createElement('h2');
  heading.textContent = file.display_path;
  panel.append(heading);
  if (file.kind === 'image') {
    const image = document.createElement('img');
    image.alt = file.display_path;
    image.src = `/api/previews/${previewId}/files/${file.id}/raw`;
    panel.append(image);
  } else if (file.kind === 'pdf') {
    const frame = document.createElement('iframe');
    frame.title = file.display_path;
    frame.src = `/api/previews/${previewId}/files/${file.id}/raw`;
    panel.append(frame);
  } else {
    const body = await request(`/api/previews/${previewId}/files/${file.id}`);
    if (body.kind === 'html') {
      const frame = document.createElement('iframe');
      frame.sandbox = body.sandbox;
      frame.srcdoc = body.rendered_html;
      panel.append(frame);
    } else {
      const article = document.createElement('article');
      article.innerHTML = body.rendered_html;
      panel.append(article);
    }
  }
  root.append(panel);
}

async function start() {
  setState('loading', '正在加载预览…');
  try {
    tg?.ready();
    tg?.expand();
    await authenticate();
    const preview = await request(`/api/previews/${previewId}`);
    root.replaceChildren();
    root.className = 'state ready';
    for (const file of preview.files) await showFile(file);
  } catch (error) {
    console.error('HermesPeek preview error', error);
    setState('error', '无法打开此预览，请返回 Telegram 后重试。');
  }
}

start();
