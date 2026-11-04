const params = new URLSearchParams(location.search);
const token = params.get('token') || '';

async function request(method, path, body) {
  const sep = path.includes('?') ? '&' : '?';
  const url = path + sep + 'token=' + encodeURIComponent(token);
  const options = { method, headers: { 'X-EasyExif-Token': token } };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const res = await fetch(url, options);
  const type = res.headers.get('content-type') || '';
  if (!res.ok) {
    let message = '请求失败 (' + res.status + ')';
    try {
      const data = await res.json();
      if (data && data.error) message = data.error;
    } catch (e) { /* ignore */ }
    throw new Error(message);
  }
  if (type.includes('application/json')) return res.json();
  return res.blob();
}

export function imageUrl(kind, size, extra) {
  const q = new URLSearchParams();
  q.set('size', String(size || 1600));
  if (extra) {
    Object.keys(extra).forEach(function (k) { q.set(k, extra[k]); });
  }
  q.set('token', token);
  return '/api/' + kind + '?' + q.toString();
}

export const api = {
  health: function () { return request('GET', '/api/health'); },
  doc: function () { return request('GET', '/api/doc'); },
  chooseFiles: async function () {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.choose_file) {
      const picked = await window.pywebview.api.choose_file();
      if (!picked) return [];
      return Array.isArray(picked) ? picked : [picked];
    }
    const res = await request('POST', '/api/dialog/choose', {});
    return res.ok && res.path ? [res.path] : [];
  },
  openDialog: function () { return request('POST', '/api/dialog/open', {}); },
  open: function (path, slot) {
    return request('POST', '/api/open', { path: path, slot: slot === undefined ? null : slot });
  },
  activate: function (index) { return request('POST', '/api/activate', { index: index }); },
  close: function (index) {
    return request('POST', '/api/close', { index: index === undefined ? null : index });
  },
  tagHelp: function (name) {
    return request('GET', '/api/tag-help?name=' + encodeURIComponent(name || ''));
  },
  formatValue: function (name, value) {
    return request('POST', '/api/format-value', { name: name, value: value });
  },
  edit: function (ops) { return request('POST', '/api/edit', { ops: ops }); },
  undo: function () { return request('POST', '/api/undo', {}); },
  redo: function () { return request('POST', '/api/redo', {}); },
  save: function (path) { return request('POST', '/api/save', { path: path || null }); },
  setXmp: function (text) { return request('POST', '/api/xmp', { text: text }); },
  segmentHex: function (index) { return request('GET', '/api/segments/' + index + '/hex'); },
  removeSegment: function (index) { return request('POST', '/api/segments/remove', { index: index }); },
  addComment: function (text) { return request('POST', '/api/segments/comment', { text: text }); },
  setGps: function (lat, lon, alt, datum) {
    return request('POST', '/api/gps', { lat: lat, lon: lon, alt: alt, datum: datum });
  },
  clearGps: function () { return request('POST', '/api/gps/clear', {}); },
  validate: function () { return request('POST', '/api/validate', {}); },
  histogram: function (index) {
    return request('GET', '/api/histogram' + (index === undefined || index === null ? '' : '?doc=' + index));
  },
  scan: function (path, recursive) {
    return request('POST', '/api/batch/scan', { path: path, recursive: recursive !== false });
  },
  exportCsv: function (files, out, profile) {
    return request('POST', '/api/batch/export', { files: files, out: out, profile: profile });
  },
  rename: function (files, pattern, apply) {
    return request('POST', '/api/batch/rename', { files: files, pattern: pattern, apply: apply });
  },
  sort: function (files, root, by, apply, move) {
    return request('POST', '/api/batch/sort', { files: files, root: root, by: by, apply: apply, move: move });
  },
  batchTemplate: function (files, template, apply) {
    return request('POST', '/api/batch/template', { files: files, template: template, apply: apply });
  },
  templates: function () { return request('GET', '/api/templates'); },
  heartbeat: function () { return request('GET', '/api/heartbeat'); }
};
