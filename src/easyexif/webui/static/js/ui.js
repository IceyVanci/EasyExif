export function $(sel, root) { return (root || document).querySelector(sel); }
export function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

export function toast(message, kind) {
  const root = $('#toastRoot');
  const node = el('div', 'toast ' + (kind || 'info'), message);
  root.appendChild(node);
  setTimeout(function () { node.classList.add('show'); }, 10);
  setTimeout(function () {
    node.classList.remove('show');
    setTimeout(function () { node.remove(); }, 240);
  }, 3200);
}

let modalStack = [];

export function modal(options) {
  const root = $('#modalRoot');
  const overlay = el('div', 'modal-overlay');
  const card = el('div', 'modal ' + (options.size || ''));
  const head = el('div', 'modal-head');
  head.appendChild(el('h3', '', options.title || ''));
  const close = el('button', 'icon-btn', '×');
  close.title = '关闭';
  head.appendChild(close);
  const body = el('div', 'modal-body');
  if (typeof options.body === 'string') body.innerHTML = options.body;
  else if (options.body) body.appendChild(options.body);
  const foot = el('div', 'modal-foot');
  const actions = options.actions || [{ label: '关闭' }];
  actions.forEach(function (action) {
    const btn = el('button', 'btn ' + (action.cls || ''), action.label);
    btn.addEventListener('click', async function () {
      if (action.onClick) {
        const result = await action.onClick();
        if (result === false) return;
      }
      closeModal();
    });
    foot.appendChild(btn);
  });
  card.appendChild(head);
  card.appendChild(body);
  if (actions.length) card.appendChild(foot);
  overlay.appendChild(card);
  root.appendChild(overlay);
  modalStack.push(overlay);
  function closeModal() {
    overlay.remove();
    modalStack = modalStack.filter(function (x) { return x !== overlay; });
        if (options.onClose) options.onClose();
  }
  close.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (event) {
    if (event.target === overlay) closeModal();
  });
  return { overlay: overlay, body: body, close: closeModal };
}

export function confirmDialog(title, message) {
  return new Promise(function (resolve) {
    modal({
      title: title,
      body: el('p', 'modal-text', message),
      actions: [
        { label: '取消', onClick: function () { resolve(false); } },
        { label: '确定', cls: 'primary', onClick: function () { resolve(true); } }
      ],
      onClose: function () { resolve(false); }
    });
  });
}

export function formatBytes(n) {
  if (!n && n !== 0) return '-';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1024 / 1024).toFixed(2) + ' MB';
}

export function debounce(fn, ms) {
  let timer = null;
  return function () {
    const args = arguments;
    clearTimeout(timer);
    timer = setTimeout(function () { fn.apply(null, args); }, ms);
  };
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function chip(status) {
  const cls = 'chip ' + String(status || '').toLowerCase();
  return el('span', cls, status || '');
}
