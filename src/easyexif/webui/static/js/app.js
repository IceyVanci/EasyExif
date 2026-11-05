import { api, imageUrl } from './api.js';
import { $, $$, el, toast, modal, confirmDialog, formatBytes, clear, chip, debounce } from './ui.js';

const state = {
  doc: null,
  tab: 'meta',
  view: 'image',
  filter: '',
  metaScope: 'shooting',
  selected: null,
  mode: 'edit',
  version: '0.1.1',
  reports: {},
  zoom: 1,
  fit: true,
  batchFiles: [],
  templates: []
};

const IFD_ORDER = ['IFD0', 'EXIF', 'GPS', 'Interop', 'IFD1', 'MakerNote', 'XMP'];
const HIDDEN_TAGS = new Set([0x8769, 0x8825, 0xA005]);
const SCOPE_IFDS = {
  general: ['IFD0', 'IFD1'],
  shooting: ['EXIF'],
  gps: ['GPS', 'Interop'],
  maker: ['MakerNote']
};
const IFD_LABEL = {
  IFD0: '主图像信息 (IFD0)',
  EXIF: '拍摄参数 (EXIF IFD)',
  GPS: 'GPS 信息 (GPS IFD)',
  Interop: '互操作信息 (Interop)',
  IFD1: '缩略图信息 (IFD1)',
  MakerNote: '厂商注释 (MakerNote)',
  XMP: 'XMP 扩展信息'
};
const STATUS_ZH = { Pass: '通过', Fail: '不通过', Suspect: '怀疑', HighSuspect: '高度怀疑', Uncertain: '未知', Missing: '缺失' };

function setStatus(text, right) {
  $('#statusText').textContent = text || '就绪';
  if (right !== undefined) $('#statusRight').textContent = right || '';
}

function setDoc(doc) {
  const previousPath = state.doc ? state.doc.path : null;
  state.doc = doc && doc.open ? doc : null;
  state.selected = null;
  if (!state.doc && state.mode === 'preview') state.mode = 'edit';
  if (state.doc && state.doc.path !== previousPath) {
    state.previewKey = null;
    showReportFor(state.doc);
  }
  renderAll();
}

function renderAll() {
  renderTop();
  renderInfo();
  renderPreview();
  renderMeta();
  renderXmp();
  renderSegments();
  renderGps();
  renderHistoryButtons();
  if (state.view === 'histogram') drawHistogram();
  renderMode();
}

function renderTop() {
  const doc = state.doc;
  const has = !!doc;
  const version = state.version ? ' ' + state.version : '';
  document.title = has ? doc.name + ' · EasyExif' + version : 'EasyExif' + version + ' · Metadata Studio';
  const meta = [];
  if (has && doc.docs && doc.docs.length > 1) meta.push('图像 ' + (doc.active_index + 1) + '/' + doc.docs.length);
  if (has) {
    meta.push(doc.format, (doc.summary.dimensions || []).join(' × '), formatBytes(doc.summary.size));
  }
  $('#fileMeta').textContent = has ? meta.join(' · ') : '打开一张 JPEG 或 TIFF 开始';
  $('#dirtyBadge').classList.toggle('hidden', !has || !doc.dirty);
  $('#rawBadge').classList.toggle('hidden', !has || !doc.readonly);
  $('#editedBadge').classList.toggle('hidden', !has || !doc.edited_by_easyexif);
  $('#btnSave').disabled = !has || !!doc.readonly;
  $('#btnClose').disabled = !has;
  $('#btnUndo').disabled = !has || !!doc.readonly || !doc.can_undo;
  $('#btnRedo').disabled = !has || !!doc.readonly || !doc.can_redo;
  $('#btnValidate').disabled = !has;
  $('#btnBatch').disabled = false;
  $('#btnExportBundle').disabled = !has;
  $('#btnReconstruct').disabled = !has || !!doc.readonly;
  $$('.quick').forEach(function (b) { b.disabled = !has || !!doc.readonly; });
  renderDocTabs();
}

function renderDocTabs() {
  const root = $('#docTabs');
  clear(root);
  const doc = state.doc;
  const docs = (doc && doc.docs) || [];
  if (!docs.length) {
    root.appendChild(el('span', 'doc-empty', '未打开文件'));
    return;
  }
  docs.forEach(function (item) {
    const tab = el('button', 'doc-tab' + (item.active ? ' active' : ''));
    tab.type = 'button';
    tab.title = item.path + (item.dirty ? '（未保存）' : '');
    tab.appendChild(el('span', 'doc-slot', String(item.index + 1)));
    tab.appendChild(el('span', 'doc-tab-name', item.name));
    if (item.dirty) {
      const dot = el('span', 'doc-dirty');
      dot.title = '有未保存的修改';
      tab.appendChild(dot);
    }
    tab.addEventListener('click', function () {
      if (!item.active) activateDoc(item.index);
    });
    root.appendChild(tab);
  });
  if (docs.length < (doc.max_docs || 2)) {
    const add = el('button', 'doc-tab add', '＋');
    add.type = 'button';
    add.title = '打开第二张图像，Ctrl+Tab 快速切换';
    add.addEventListener('click', openDialog);
    root.appendChild(add);
  }
}

async function activateDoc(index) {
  if (!state.doc || index === state.doc.active_index) return;
  try {
    const res = await api.activate(index);
    setDoc(res.doc);
    setStatus('已切换到 ' + res.doc.name, res.doc.format);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function cycleDoc() {
  const doc = state.doc;
  const docs = (doc && doc.docs) || [];
  if (docs.length < 2) return;
  activateDoc((doc.active_index + 1) % docs.length);
}

// ---------------------------------------------------------------------------
// Preview / edit mode
// ---------------------------------------------------------------------------
function setMode(mode) {
  state.mode = mode === 'preview' ? 'preview' : 'edit';
  renderMode();
  setStatus(state.mode === 'preview' ? '预览模式：仅查看，编辑已禁用' : '编辑模式');
}

function toggleMode() {
  if (!state.doc) return;
  setMode(state.mode === 'preview' ? 'edit' : 'preview');
}

function renderMode() {
  const doc = state.doc;
  const preview = state.mode === 'preview' && !!doc;
  const readonly = !!(doc && doc.readonly);
  const editable = !!doc && !preview && !readonly;
  $('#app').classList.toggle('mode-preview', preview);
  $('#readonlyBadge').classList.toggle('hidden', !preview || readonly);
  const sw = $('#modeSwitch');
  sw.setAttribute('aria-checked', preview ? 'true' : 'false');
  sw.disabled = !doc || readonly;
  sw.title = readonly ? 'RAW 只读文件' : (preview ? '当前：预览模式（仅查看，编辑已禁用）' : '当前：编辑模式（点击进入只读预览）');

  $('#btnSave').disabled = !editable;
  $('#btnUndo').disabled = !editable || !doc.can_undo;
  $('#btnRedo').disabled = !editable || !doc.can_redo;
  $('#btnBatch').disabled = preview;
  $('#btnReconstruct').disabled = !doc || readonly;
  $('#btnAddTag').disabled = !editable;
  $('#btnDeleteTag').disabled = !editable;
  $('#btnApplyXmp').disabled = !editable;
  $('#btnAddComment').disabled = !editable;
  $('#btnClearGps').disabled = !editable;
  $('#xmpText').readOnly = !editable;
  ['gpsLat', 'gpsLon', 'gpsAlt', 'gpsDatum'].forEach(function (id) {
    $('#' + id).disabled = !editable;
  });
  const gpsSubmit = $('#gpsForm button[type="submit"]');
  if (gpsSubmit) gpsSubmit.disabled = !editable;
  $$('.quick').forEach(function (b) {
    b.disabled = !doc || (preview && b.dataset.quick !== 'validate') || (readonly && b.dataset.quick !== 'validate');
  });
}

function renderInfo() {
  const doc = state.doc;
  if (!doc) {
    ['infoFormat', 'infoSize', 'infoBytes', 'infoCamera', 'infoLens', 'infoDate', 'infoLensDb'].forEach(function (id) {
      $('#' + id).textContent = '—';
    });
    $('#infoLensDb').title = '';
    return;
  }
  const cam = doc.summary.camera || {};
  const exp = doc.summary.exposure || {};
  $('#infoFormat').textContent = doc.format;
  $('#infoSize').textContent = (doc.summary.dimensions || []).join(' × ');
  $('#infoBytes').textContent = formatBytes(doc.summary.size);
  $('#infoCamera').textContent = [cam.make, cam.model].filter(Boolean).join(' ') || '—';
  $('#infoLens').textContent = cam.lens || '—';
  $('#infoDate').textContent = exp.date || '—';
  const lens = doc.lens || {};
  let lensText = '未加载';
  if (lens.available) {
    if (lens.lens && lens.lens.model) {
      lensText = lens.lens.model + (lens.category ? ' · ' + lens.category : '');
    } else {
      lensText = '未匹配';
    }
    if (lens.warnings && lens.warnings.length) lensText = '⚠ ' + lensText;
  }
  $('#infoLensDb').textContent = lensText;
  $('#infoLensDb').title = lens.warnings && lens.warnings.length ? lens.warnings.join('\n') : (lens.source || '');
}

function renderPreview() {
  const img = $('#preview');
  const empty = $('#emptyState');
  if (!state.doc) {
    img.classList.add('hidden');
    img.removeAttribute('src');
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  img.classList.remove('hidden');
  const key = state.doc.path + ':' + state.doc.summary.size + ':' + state.doc.active_index;
  if (state.previewKey === key) return;
  state.previewKey = key;
  state.previewRetry = 0;
  img.onload = function () { state.previewRetry = 0; applyZoom(); };
  img.onerror = function () {
    if (state.previewRetry < 2) {
      state.previewRetry += 1;
      setTimeout(function () {
        img.src = imageUrl('preview', 1800, { v: Date.now(), doc: state.doc.active_index });
      }, 500);
      return;
    }
    toast('无法生成预览', 'error');
  };
  img.src = imageUrl('preview', 1800, { v: Date.now(), doc: state.doc.active_index });
}

function applyZoom() {
  const img = $('#preview');
  if (!img.src) return;
  img.style.transform = state.fit ? 'none' : 'scale(' + state.zoom.toFixed(2) + ')';
  img.style.cursor = state.fit ? 'default' : 'grab';
  $('#zoomLabel').textContent = state.fit ? '适应窗口' : Math.round(state.zoom * 100) + '%';
}

function renderHistoryButtons() {
  const doc = state.doc;
  $('#btnUndo').disabled = !doc || !doc.can_undo;
  $('#btnRedo').disabled = !doc || !doc.can_redo;
}

// ---------------------------------------------------------------------------
// Metadata table
// ---------------------------------------------------------------------------
function filteredRows() {
  if (!state.doc) return [];
  const q = state.filter.trim().toLowerCase();
  const source = state.doc.rows;
  const hasFNumber = source.some(function (row) {
    return row.ifd === 'EXIF' && row.name === 'FNumber';
  });
  const hasExposureTime = source.some(function (row) {
    return row.ifd === 'EXIF' && row.name === 'ExposureTime';
  });
  return source.filter(function (row) {
    if (row.ifd === 'XMP') return false;
    if (typeof row.tag === 'number' && HIDDEN_TAGS.has(row.tag)) return false;
    const scope = state.metaScope;
    if (scope === 'shooting' && row.ifd === 'EXIF') {
      // APEX tags are storage details. Hide the duplicate technical row when
      // the natural tag is available; keep it as a read-only fallback if not.
      if (row.name === 'ApertureValue' && hasFNumber) return false;
      if (row.name === 'ShutterSpeedValue' && hasExposureTime) return false;
      if (row.name === 'BrightnessValue') return false;
    }
    if (scope !== 'all' && SCOPE_IFDS[scope] && SCOPE_IFDS[scope].indexOf(row.ifd) === -1) return false;
    if (!q) return true;
    return ((row.label || row.name) + ' ' + row.name + ' ' + row.value + ' ' + row.tag + ' ' + row.ifd).toLowerCase().includes(q);
  });
}

function renderMeta() {
  const root = $('#metaTable');
  clear(root);
  const rows = filteredRows();
  if (!rows.length) {
    const empty = el('div', 'empty-row', state.doc ? '没有匹配的标签' : '打开文件后显示元数据');
    root.appendChild(empty);
    return;
  }
  const table = el('table');
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  ['项目', '值', '标签号', '标签名', '数据类型', '组件数', '字节'].forEach(function (t) {
    const th = document.createElement('th');
    th.textContent = t;
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  IFD_ORDER.forEach(function (ifd) {
    const group = rows.filter(function (r) { return r.ifd === ifd; });
    if (!group.length) return;
    const gr = document.createElement('tr');
    gr.className = 'group-row';
    const gd = document.createElement('td');
    gd.colSpan = 7;
    gd.textContent = IFD_LABEL[ifd] || ifd;
    gr.appendChild(gd);
    tbody.appendChild(gr);
    group.forEach(function (row) {
      const tr = document.createElement('tr');
      tr.dataset.ifd = row.ifd;
      tr.dataset.name = row.name;
      tr.dataset.tag = row.tag;
      if (row.readonly) tr.classList.add('readonly-row');
      if (state.selected && state.selected.ifd === row.ifd && state.selected.name === row.name) {
        tr.classList.add('selected');
      }
      const t1 = el('td', 'label', row.label || row.name);
      t1.title = row.label || row.name;
      const t2 = el('td', 'value');
      t2.appendChild(document.createTextNode(row.value));
      if (row.technical) {
        const tech = el('span', 'tech-value', row.technical);
        tech.title = '技术字段（只读）';
        t2.appendChild(tech);
      }
      t2.title = row.technical ? row.value + ' · ' + row.technical : row.value;
      const t3 = el('td', 'mono tagcell', typeof row.tag === 'number'
        ? row.tag.toString(16).toUpperCase().padStart(4, '0') : row.tag);
      const t4 = el('td', 'tagname', row.name);
      t4.title = row.name;
      const t5 = el('td', 'typecell', row.type);
      const t6 = el('td', 'numcell', row.count);
      const t7 = el('td', 'numcell', row.bytes === null || row.bytes === undefined ? '' : row.bytes);
      tr.appendChild(t1);
      tr.appendChild(t2);
      tr.appendChild(t3);
      tr.appendChild(t4);
      tr.appendChild(t5);
      tr.appendChild(t6);
      tr.appendChild(t7);
      tr.addEventListener('click', function () {
        state.selected = row;
        $$('#metaTable tr.selected').forEach(function (x) { x.classList.remove('selected'); });
        tr.classList.add('selected');
      });
      tr.addEventListener('dblclick', function () { openEdit(row); });
      tbody.appendChild(tr);
    });
  });
  table.appendChild(tbody);
  root.appendChild(table);
}

function editValue(row) {
  if (row.name === 'FNumber') return String(row.value).replace(/^f\//, '');
  if (row.name === 'ExposureTime') return String(row.value).replace(/\s*s$/, '');
  const raw = row.raw;
  if (row.type === 'UNDEFINED' || row.type === 'BYTE') return row.value;
  if (raw === null || raw === undefined) return row.value;
  if (typeof raw === 'number') return String(raw);
  if (typeof raw === 'string') return raw;
  if (Array.isArray(raw)) {
    if (raw.length === 2 && raw.every(function (x) { return typeof x === 'number'; })) {
      return raw[0] + '/' + raw[1];
    }
    if (raw.every(function (x) { return Array.isArray(x); })) {
      return raw.map(function (pair) { return pair.join('/'); }).join(' ');
    }
    return raw.join(' ');
  }
  return row.value;
}

function ensureEditable() {
  if (!state.doc) return false;
  if (state.doc.readonly) {
    toast('RAW 文件当前为只读模式', 'info');
    return false;
  }
  if (state.mode === 'preview') {
    toast('预览模式已禁用编辑，切回编辑模式后可修改', 'info');
    return false;
  }
  return true;
}

function openEdit(row) {
  if (!ensureEditable()) return;
  if (row.ifd === 'MakerNote') {
    toast('厂商注释字段为只读', 'info');
    return;
  }
  if (row.readonly) {
    const redirect = row.name === 'ApertureValue' ? 'FNumber'
      : row.name === 'ShutterSpeedValue' ? 'ExposureTime' : '';
    if (redirect) {
      const natural = state.doc.rows.find(function (r) {
        return r.ifd === 'EXIF' && r.name === redirect;
      });
      if (natural) {
        toast('技术字段只读，已转到 ' + redirect, 'info');
        openEdit(natural);
        return;
      }
      const naturalName = redirect === 'FNumber' ? 'EXIF.FNumber' : 'EXIF.ExposureTime';
      const naturalValue = redirect === 'FNumber'
        ? String(row.value).replace(/^f\//, '')
        : String(row.value).replace(/\s*s$/, '');
      toast('技术字段只读，正在添加 ' + redirect + ' 自然值', 'info');
      openTagEditor({
        title: redirect === 'FNumber' ? '添加光圈 F 数' : '添加快门时间',
        action: '添加',
        name: naturalName,
        value: naturalValue,
        onSave: function (tagName, tagValue) {
          return applyOps([{ op: 'set', name: tagName, value: tagValue }], '已更新 ' + tagName);
        }
      });
      return;
    }
    const reason = row.name === 'BrightnessValue' ? '亮度是只读技术字段'
      : row.name === 'MaxApertureValue' ? '最大光圈是只读技术字段'
      : '技术字段只读';
    toast(reason, 'info');
    return;
  }
  const name = row.ifd === 'XMP' ? 'XMP.' + row.name : row.ifd + '.' + row.name;
  openTagEditor({
    title: '编辑元数据',
    action: '保存',
    name: name,
    value: editValue(row),
    onSave: function (tagName, tagValue) {
      return applyOps([{ op: 'set', name: tagName, value: tagValue }], '已更新 ' + tagName);
    }
  });
}

function openAddTag() {
  if (!ensureEditable()) return;
  openTagEditor({
    title: '添加标签',
    action: '添加',
    name: '',
    value: '',
    placeholder: 'IFD0.Artist、EXIF.FNumber 或 XMP.dc:title',
    onSave: function (tagName, tagValue) {
      return applyOps([{ op: 'set', name: tagName, value: tagValue }], '已添加标签');
    }
  });
}

function openTagEditor(config) {
  const wrap = el('div', 'edit-form');
  const nameField = document.createElement('label');
  nameField.className = 'field';
  nameField.appendChild(el('span', 'field-label', '标签'));
  const nameInput = el('input', 'input mono-input');
  nameInput.value = config.name || '';
  nameInput.placeholder = config.placeholder || 'EXIF.FNumber';
  nameInput.spellcheck = false;
  nameField.appendChild(nameInput);
  const tagMeta = el('div', 'tag-meta');
  nameField.appendChild(tagMeta);

  const valueField = document.createElement('label');
  valueField.className = 'field';
  valueField.appendChild(el('span', 'field-label', '值'));
  const valueInput = el('input', 'input mono-input');
  valueInput.value = config.value === undefined || config.value === null ? '' : String(config.value);
  valueInput.spellcheck = false;
  valueField.appendChild(valueInput);

  const preview = el('div', 'edit-preview hidden');
  const hint = el('div', 'edit-hint');
  wrap.appendChild(nameField);
  wrap.appendChild(valueField);
  wrap.appendChild(preview);
  wrap.appendChild(hint);

  let helpSeq = 0;
  let previewSeq = 0;

  function renderHelp(data) {
    clear(tagMeta);
    clear(hint);
    const meta = [];
    if (data.ifd) meta.push(data.ifd);
    if (data.tag) meta.push(data.tag);
    if (data.type) meta.push(data.type);
    if (data.readonly) meta.push('只读');
    tagMeta.textContent = meta.join(' · ');
    if (data.desc) hint.appendChild(el('p', 'hint-desc', data.desc));
    valueInput.readOnly = !!data.readonly;
    valueInput.title = data.readonly ? '技术字段为只读；请编辑对应的自然值' : '';
    if (data.format) {
      const row = el('div', 'hint-row');
      row.appendChild(el('span', 'hint-key', '输入格式'));
      row.appendChild(el('span', 'hint-val', data.format));
      hint.appendChild(row);
    }
    const options = data.options || [];
    if (options.length) {
      const row = el('div', 'hint-row options');
      row.appendChild(el('span', 'hint-key', '常用值'));
      const list = el('div', 'hint-chips');
      options.forEach(function (option) {
        const button = el('button', 'hint-chip', option.label);
        button.type = 'button';
        button.title = '写入原始值 ' + option.value;
        button.addEventListener('click', function () {
          valueInput.value = option.value;
          refreshPreview();
          valueInput.focus();
        });
        list.appendChild(button);
      });
      row.appendChild(list);
      hint.appendChild(row);
    }
    if (!hint.childNodes.length) {
      hint.appendChild(el('p', 'muted', '没有该标签的专用说明。'));
    }
  }

  async function refreshHelp() {
    const seq = ++helpSeq;
    const name = nameInput.value.trim();
    try {
      const res = await api.tagHelp(name);
      if (seq === helpSeq) renderHelp(res.data || {});
    } catch (err) {
      if (seq !== helpSeq) return;
      clear(hint);
      hint.appendChild(el('p', 'muted', '无法获取标签说明：' + err.message));
    }
  }

  async function refreshPreview() {
    const seq = ++previewSeq;
    const name = nameInput.value.trim();
    const value = valueInput.value;
    clear(preview);
    preview.className = 'edit-preview';
    if (!name) {
      preview.classList.add('hidden');
      return;
    }
    preview.classList.remove('hidden');
    if (value === '') {
      preview.classList.add('muted');
      preview.textContent = '值为空，保存后会写入空内容。';
      return;
    }
    preview.classList.add('pending');
    preview.textContent = '正在解析…';
    try {
      const res = await api.formatValue(name, value);
      if (seq !== previewSeq) return;
      const data = res.data || {};
      preview.className = 'edit-preview ok';
      clear(preview);
      const main = el('div', 'preview-main');
      main.appendChild(el('span', 'preview-key', '将写入'));
      main.appendChild(el('span', 'preview-val', data.display === undefined ? value : data.display));
      if (data.count > 1) main.appendChild(el('span', 'preview-count', data.count + ' 个分量'));
      preview.appendChild(main);
      if (data.technical) {
        preview.appendChild(el('div', 'preview-tech', '技术值：' + data.technical));
      }
      (data.derived || []).forEach(function (item) {
        const row = el('div', 'preview-derived');
        row.appendChild(el('span', 'preview-key', '关联'));
        row.appendChild(el('span', 'preview-name', item.name));
        row.appendChild(el('span', 'preview-val', item.display));
        preview.appendChild(row);
      });
      if (data.note) preview.appendChild(el('div', 'preview-note', data.note));
    } catch (err) {
      if (seq !== previewSeq) return;
      preview.className = 'edit-preview bad';
      preview.textContent = '无法解析：' + err.message;
    }
  }

  nameInput.addEventListener('input', debounce(function () {
    refreshHelp();
    refreshPreview();
  }, 220));
  valueInput.addEventListener('input', debounce(refreshPreview, 180));

  refreshHelp();
  refreshPreview();

  modal({
    title: config.title,
    body: wrap,
    actions: [
      { label: '取消' },
      { label: config.action, cls: 'primary', onClick: async function () {
        const name = nameInput.value.trim();
        if (!name) {
          toast('请填写标签名', 'error');
          nameInput.focus();
          return false;
        }
        return config.onSave(name, valueInput.value);
      } }
    ]
  });
}

function deleteSelected() {
  if (!ensureEditable()) return;
  if (!state.selected) {
    toast('先选择一个标签', 'info');
    return;
  }
  const row = state.selected;
  if (row.ifd === 'MakerNote') {
    toast('厂商注释字段为只读', 'info');
    return;
  }
  const name = row.ifd === 'XMP' ? 'XMP.' + row.name : row.ifd + '.' + row.name;
  confirmDialog('删除标签', '确定删除 ' + name + ' ？').then(function (ok) {
    if (!ok) return;
    applyOps([{ op: 'delete', name: name }], '已删除 ' + name);
  });
}

async function applyOps(ops, message) {
  if (!ensureEditable()) return false;
  try {
    const res = await api.edit(ops);
    delete state.reports[res.doc.path];
    setDoc(res.doc);
    if (state.tab === 'validate') showReportFor(res.doc);
    if (message) toast(message, 'success');
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}

// ---------------------------------------------------------------------------
// XMP
// ---------------------------------------------------------------------------
function renderXmp() {
  const area = $('#xmpText');
  if (!state.doc) { area.value = ''; return; }
  area.value = state.doc.xmp.text || '';
}

async function applyXmp() {
  if (!ensureEditable()) return;
  try {
    const res = await api.setXmp($('#xmpText').value);
    delete state.reports[res.doc.path];
    setDoc(res.doc);
    if (state.tab === 'validate') showReportFor(res.doc);
    toast('XMP 已应用', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Segments
// ---------------------------------------------------------------------------
function renderSegments() {
  const root = $('#segmentTable');
  clear(root);
  if (!state.doc) {
    root.appendChild(el('div', 'empty-row', '打开 JPEG 后显示段列表'));
    $('#segmentCount').textContent = '0 个段';
    return;
  }
  const segs = state.doc.segments || [];
  $('#segmentCount').textContent = segs.length + ' 个段';
  if (!segs.length) {
    root.appendChild(el('div', 'empty-row', '这不是 JPEG，或没有可显示的段'));
    return;
  }
  const table = el('table');
  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  ['#', '类型', '大小'].forEach(function (t) {
    const th = document.createElement('th');
    th.textContent = t;
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  segs.forEach(function (seg) {
    const tr = document.createElement('tr');
    tr.appendChild(el('td', 'mono', seg.index));
    tr.appendChild(el('td', '', seg.label));
    tr.appendChild(el('td', 'mono', formatBytes(seg.size)));
    tr.title = '双击查看十六进制';
    tr.addEventListener('dblclick', function () { showHex(seg.index); });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  root.appendChild(table);
}

async function showHex(index) {
  try {
    const res = await api.segmentHex(index);
    const data = res.data;
    const pre = el('pre', 'hex-view');
    pre.style.fontFamily = 'var(--mono)';
    pre.style.fontSize = '11px';
    pre.style.lineHeight = '1.5';
    pre.style.maxHeight = '60vh';
    pre.style.overflow = 'auto';
    pre.textContent = data.lines.map(function (line) {
      return line.offset.toString(16).toUpperCase().padStart(8, '0') + '  ' + line.hex.padEnd(47, ' ') + '  ' + line.ascii;
    }).join('\n');
    modal({ title: data.label + ' · ' + data.size + ' bytes', size: 'large', body: pre, actions: [{ label: '关闭' }] });
  } catch (err) {
    toast(err.message, 'error');
  }
}

function removeSelectedSegment() {
  if (!ensureEditable()) return;
  const index = window.prompt('要删除的段序号（见列表第一列）');
  if (index === null) return;
  const n = parseInt(index, 10);
  if (isNaN(n)) { toast('序号无效', 'error'); return; }
  confirmDialog('删除段', '确定删除第 ' + n + ' 段？此操作可撤销。').then(function (ok) {
    if (ok) applyOps([{ op: 'remove_segment', index: n }], '已删除段 ' + n);
  });
}

function addComment() {
  if (!ensureEditable()) return;
  const text = window.prompt('COM 注释内容');
  if (!text) return;
  applyOps([{ op: 'add_comment', text: text }], '已添加注释段');
}

// ---------------------------------------------------------------------------
// GPS
// ---------------------------------------------------------------------------
function renderGps() {
  const view = $('#gpsView');
  clear(view);
  const links = $('#mapLinks');
  clear(links);
  const gps = state.doc && state.doc.gps;
  if (!gps) {
    view.appendChild(el('p', 'muted', '当前文件没有 GPS 数据。'));
    return;
  }
  const lat = Number(gps.latitude);
  const lon = Number(gps.longitude);
  const block = document.createElement('div');
  block.appendChild(el('strong', '', 'WGS-84 坐标'));
  block.appendChild(el('div', '', lat.toFixed(7) + ', ' + lon.toFixed(7)));
  if (gps.altitude !== null && gps.altitude !== undefined) {
    block.appendChild(el('div', 'muted', '海拔 ' + Number(gps.altitude).toFixed(1) + ' m'));
  }
  if (gps.date || gps.timestamp) {
    block.appendChild(el('div', 'muted', [gps.date, gps.timestamp].filter(Boolean).join(' ')));
  }
  view.appendChild(block);
  $('#gpsLat').value = lat.toFixed(7);
  $('#gpsLon').value = lon.toFixed(7);
  $('#gpsAlt').value = gps.altitude === null || gps.altitude === undefined ? '' : Number(gps.altitude).toFixed(1);

  const providers = [
    ['OpenStreetMap', 'https://www.openstreetmap.org/?mlat=' + lat + '&mlon=' + lon + '#map=15/' + lat + '/' + lon],
    ['Google', 'https://www.google.com/maps?q=' + lat + ',' + lon],
    ['百度', 'https://api.map.baidu.com/marker?location=' + lat + ',' + lon + '&title=EasyExif&content=EasyExif&output=html&coord_type=wgs84'],
    ['高德', 'https://uri.amap.com/marker?position=' + lon + ',' + lat + '&name=EasyExif']
  ];
  providers.forEach(function (p) {
    const a = el('a', '', p[0]);
    a.href = p[1];
    a.target = '_blank';
    a.rel = 'noreferrer';
    links.appendChild(a);
  });
}

async function submitGps(event) {
  event.preventDefault();
  if (!ensureEditable()) return;
  const lat = parseFloat($('#gpsLat').value);
  const lon = parseFloat($('#gpsLon').value);
  const alt = $('#gpsAlt').value === '' ? null : parseFloat($('#gpsAlt').value);
  if (isNaN(lat) || isNaN(lon)) { toast('请输入有效的经纬度', 'error'); return; }
  try {
    const res = await api.setGps(lat, lon, alt, $('#gpsDatum').value);
    setDoc(res.doc);
    toast('GPS 已写入', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function clearGps() {
  if (!ensureEditable()) return;
  const ok = await confirmDialog('移除 GPS', '确定移除当前文件的 GPS 数据？');
  if (!ok) return;
  try {
    const res = await api.clearGps();
    setDoc(res.doc);
    toast('GPS 已移除', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------
function showReportFor(doc) {
  const box = $('#validateResult');
  clear(box);
  const report = doc && state.reports[doc.path];
  if (report) {
    renderReport(report);
    return;
  }
  box.appendChild(el('p', 'muted', '点击“开始校验”生成原图可信度报告。'));
}

async function runValidate() {
  if (!state.doc) return;
  const path = state.doc.path;
  const box = $('#validateResult');
  clear(box);
  box.appendChild(el('p', 'muted', '正在分析，请稍候…'));
  selectTab('validate');
  try {
    const res = await api.validate();
    if (!state.doc || state.doc.path !== path) return;
    state.reports[path] = res.report;
    renderReport(res.report);
  } catch (err) {
    if (!state.doc || state.doc.path !== path) return;
    clear(box);
    box.appendChild(el('p', 'muted', '校验失败：' + err.message));
  }
}

function renderReport(report) {
  const box = $('#validateResult');
  clear(box);
  const checks = report.checks || [];
  const unknown = report.available === false || report.score === null || report.score === undefined;
  const card = el('div', 'score-card');
  const score = el('div', 'score ' + (unknown ? 's0' : 's' + report.score), unknown ? '?' : String(report.score));
  const text = el('div', 'score-text');
  text.appendChild(el('strong', '', report.rating || (unknown ? '未知' : report.score + ' 级')));
  text.appendChild(el('div', 'muted', report.summary || ''));
  card.appendChild(score);
  card.appendChild(text);
  box.appendChild(card);
  if (unknown) {
    box.appendChild(el('div', 'check-summary muted',
      checks.length + ' 项检查 · 缺少 EXIF，无法评估等级'));
  } else {
    const passed = checks.filter(function (c) { return c.status === 'Pass'; }).length;
    box.appendChild(el('div', 'check-summary muted', checks.length + ' 项检查 · ' + passed + ' 项通过'));
  }
  checks.forEach(function (check) {
    const row = el('div', 'check');
    row.appendChild(el('div', 'check-title', check.title));
    const c = el('span', 'chip ' + String(check.status || '').toLowerCase(),
                  STATUS_ZH[check.status] || check.status);
    row.appendChild(c);
    row.appendChild(el('div', 'check-detail', check.detail || ''));
    box.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Batch
// ---------------------------------------------------------------------------
async function openBatch() {
  if (state.mode === 'preview') {
    toast('预览模式已禁用批处理，切回编辑模式后可执行', 'info');
    return;
  }
  const body = document.createElement('div');
  body.className = 'batch-body';

  const pathRow = document.createElement('div');
  pathRow.className = 'panel-tools';
  const pathInput = el('input', 'input');
  pathInput.placeholder = '文件夹或图像路径，例如 F:\\Photos';
  const scanBtn = el('button', 'btn small', '扫描');
  pathRow.appendChild(pathInput);
  pathRow.appendChild(scanBtn);
  body.appendChild(pathRow);

  const info = el('p', 'muted', '先扫描文件夹，再选择操作。');
  body.appendChild(info);

  const options = document.createElement('div');
  options.className = 'form-grid';
  const profileLabel = el('label', '', 'CSV 配置');
  const profileSelect = document.createElement('select');
  profileSelect.className = 'input';
  ['simple', 'detailed', 'photography', 'gps', 'file'].forEach(function (p) {
    const o = document.createElement('option');
    o.value = p;
    o.textContent = p;
    profileSelect.appendChild(o);
  });
  profileLabel.appendChild(profileSelect);
  const outLabel = el('label', '', 'CSV 输出路径');
  const outInput = el('input', 'input');
  outInput.placeholder = 'F:\\Photos\\report.csv';
  outLabel.appendChild(outInput);
  const patternLabel = el('label', '', '重命名模板');
  const patternInput = el('input', 'input');
  patternInput.value = '{date}_{seq:03d}.{ext}';
  patternLabel.appendChild(patternInput);
  const sortLabel = el('label', '', '分拣方式');
  const sortSelect = document.createElement('select');
  sortSelect.className = 'input';
  [['date', '按日期'], ['camera', '按相机'], ['lens', '按镜头'], ['month', '按月份']].forEach(function (p) {
    const o = document.createElement('option');
    o.value = p[0];
    o.textContent = p[1];
    sortSelect.appendChild(o);
  });
  sortLabel.appendChild(sortSelect);
  const rootLabel = el('label', '', '分拣目标目录');
  const rootInput = el('input', 'input');
  rootInput.placeholder = 'F:\\Photos\\sorted';
  rootLabel.appendChild(rootInput);
  const templateLabel = el('label', '', '元数据模板');
  const templateSelect = document.createElement('select');
  templateSelect.className = 'input';
  templateLabel.appendChild(templateSelect);
  options.appendChild(profileLabel);
  options.appendChild(outLabel);
  options.appendChild(patternLabel);
  options.appendChild(sortLabel);
  options.appendChild(rootLabel);
  options.appendChild(templateLabel);
  body.appendChild(options);

  const applyLabel = el('label', 'check-line');
  const applyCheck = document.createElement('input');
  applyCheck.type = 'checkbox';
  applyLabel.appendChild(applyCheck);
  applyLabel.appendChild(document.createTextNode(' 实际执行（不勾选为干跑预览）'));
  body.appendChild(applyLabel);

  const actions = document.createElement('div');
  actions.className = 'panel-tools';
  const exportBtn = el('button', 'btn small primary', '导出 CSV');
  const renameBtn = el('button', 'btn small', '重命名');
  const sortBtn = el('button', 'btn small', '分拣');
  const templateBtn = el('button', 'btn small', '套模板');
  actions.appendChild(exportBtn);
  actions.appendChild(renameBtn);
  actions.appendChild(sortBtn);
  actions.appendChild(templateBtn);
  body.appendChild(actions);

  const result = el('div', 'table-wrap');
  result.style.maxHeight = '300px';
  result.appendChild(el('div', 'empty-row', '扫描后显示文件'));
  body.appendChild(result);

  const m = modal({ title: '批处理', size: 'large', body: body, actions: [{ label: '关闭' }] });

  try {
    const res = await api.templates();
    state.templates = res.data || [];
    state.templates.forEach(function (t) {
      const o = document.createElement('option');
      o.value = t.name;
      o.textContent = t.name + ' · ' + t.description;
      templateSelect.appendChild(o);
    });
  } catch (err) { /* ignore */ }

  function renderFiles(files, total) {
    clear(result);
    const table = el('table');
    const thead = document.createElement('thead');
    const hr = document.createElement('tr');
    ['文件名', '路径', '大小'].forEach(function (t) {
      const th = document.createElement('th');
      th.textContent = t;
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    files.slice(0, 300).forEach(function (f) {
      const tr = document.createElement('tr');
      tr.appendChild(el('td', '', f.name));
      tr.appendChild(el('td', 'mono', f.path));
      tr.appendChild(el('td', 'mono', formatBytes(f.size)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    result.appendChild(table);
    info.textContent = '共 ' + total + ' 个文件' + (files.length < total ? '（仅显示前 ' + files.length + ' 个）' : '');
  }

  scanBtn.addEventListener('click', async function () {
    try {
      info.textContent = '正在扫描…';
      const res = await api.scan(pathInput.value.trim(), true);
      state.batchFiles = res.data.files;
      renderFiles(state.batchFiles, res.data.total);
    } catch (err) {
      toast(err.message, 'error');
      info.textContent = '扫描失败';
    }
  });

  exportBtn.addEventListener('click', async function () {
    try {
      const res = await api.exportCsv(state.batchFiles.map(function (f) { return f.path; }), outInput.value.trim(), profileSelect.value);
      toast('已导出 ' + res.data.rows + ' 行', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });

  renameBtn.addEventListener('click', async function () {
    try {
      const res = await api.rename(state.batchFiles.map(function (f) { return f.path; }), patternInput.value.trim(), applyCheck.checked);
      const plan = res.data.plan || [];
      clear(result);
      const table = el('table');
      const thead = document.createElement('thead');
      const hr = document.createElement('tr');
      ['原文件', '目标'].forEach(function (t) {
        const th = document.createElement('th');
        th.textContent = t;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);
      const tbody = document.createElement('tbody');
      plan.slice(0, 300).forEach(function (p) {
        const tr = document.createElement('tr');
        tr.appendChild(el('td', 'mono', p.src));
        tr.appendChild(el('td', 'mono', p.dst || p.error || ''));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      result.appendChild(table);
      toast(applyCheck.checked ? '重命名完成' : '干跑预览，共 ' + plan.length + ' 项', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });

  sortBtn.addEventListener('click', async function () {
    try {
      const res = await api.sort(state.batchFiles.map(function (f) { return f.path; }), rootInput.value.trim(), sortSelect.value, applyCheck.checked, false);
      toast(applyCheck.checked ? '分拣完成' : '干跑预览，共 ' + (res.data.plan || []).length + ' 项', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });

  templateBtn.addEventListener('click', async function () {
    try {
      const res = await api.batchTemplate(state.batchFiles.map(function (f) { return f.path; }), templateSelect.value, applyCheck.checked);
      const results = res.data.results || [];
      const ok = results.filter(function (r) { return !r.error; }).length;
      toast((applyCheck.checked ? '已处理 ' : '干跑：') + ok + ' 个文件', 'success');
    } catch (err) { toast(err.message, 'error'); }
  });
}

// ---------------------------------------------------------------------------
// Histogram
// ---------------------------------------------------------------------------
async function drawHistogram() {
  const canvas = $('#histogramCanvas');
  if (!state.doc) return;
  try {
    const res = await api.histogram(state.doc.active_index);
    const bins = res.data.bins;
    const W = canvas.width;
    const H = canvas.height;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    const max = Math.max.apply(null, bins) || 1;
    const barW = W / bins.length;
    const gradient = ctx.createLinearGradient(0, H, 0, 0);
    gradient.addColorStop(0, 'rgba(79,70,229,.35)');
    gradient.addColorStop(1, 'rgba(79,70,229,.95)');
    ctx.fillStyle = gradient;
    bins.forEach(function (v, i) {
      const h = (v / max) * (H - 30);
      ctx.fillRect(i * barW, H - 20 - h, Math.max(1, barW - 0.4), h);
    });
    ctx.strokeStyle = 'rgba(148,163,184,.5)';
    ctx.beginPath();
    ctx.moveTo(0, H - 20);
    ctx.lineTo(W, H - 20);
    ctx.stroke();
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px Segoe UI';
    ctx.fillText('均值 ' + res.data.mean.toFixed(1), 12, 20);
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Tabs / views / theme
// ---------------------------------------------------------------------------
function selectTab(name) {
  state.tab = name;
  $$('#inspectorTabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === name); });
  $$('.tab-panel').forEach(function (p) { p.classList.toggle('active', p.dataset.panel === name); });
}

function selectView(name) {
  state.view = name;
  $$('#viewTabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.view === name); });
  $('#canvas').classList.toggle('hidden', name !== 'image');
  $('#histogramView').classList.toggle('hidden', name !== 'histogram');
  if (name === 'histogram') drawHistogram();
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('easyexif-theme', next);
}

// ---------------------------------------------------------------------------
// Events / init
// ---------------------------------------------------------------------------
function askReplace() {
  return new Promise(function (resolve) {
    modal({
      title: '替换当前图像',
      body: el('p', 'modal-text', '已同时打开两张图像，新文件会替换当前显示的图像，另一张仍然保留。'),
      actions: [
        { label: '取消', onClick: function () { resolve('cancel'); } },
        { label: '不保存并替换', cls: 'danger', onClick: function () { resolve('discard'); } },
        { label: '保存并替换', cls: 'primary', onClick: function () { resolve('save'); } }
      ],
      onClose: function () { resolve('cancel'); }
    });
  });
}

async function openPaths(paths) {
  const picked = (paths || []).filter(Boolean);
  if (!picked.length) return;
  const docs = (state.doc && state.doc.docs) || [];
  let queue = picked.slice();
  if (docs.length >= 2) {
    queue = queue.slice(0, 1);
    if (state.doc && state.doc.dirty) {
      const choice = await askReplace();
      if (choice === 'cancel') return;
      if (choice === 'save' && !(await saveDoc({ force: true }))) return;
    }
  } else {
    queue = queue.slice(0, 2 - docs.length);
  }
  let last = null;
  for (let i = 0; i < queue.length; i += 1) {
    const path = queue[i];
    try {
      setStatus('正在打开 ' + path + '…');
      const res = await api.open(path);
      if (!res.ok || !res.doc) throw new Error((res && res.error) || '打开失败');
      last = res.doc;
    } catch (err) {
      toast(err.message, 'error');
      setStatus('打开失败');
    }
  }
  if (!last) return;
  setDoc(last);
  if (queue.length > 1) toast('已同时打开 ' + last.docs.length + ' 张图像，Ctrl+Tab 切换', 'success');
  else toast('已打开 ' + last.name, 'success');
  setStatus('已打开 ' + last.path, last.format);
}

async function openDialog() {
  try {
    setStatus('等待选择文件…');
    const picked = await api.chooseFiles();
    if (!picked.length) {
      setStatus('就绪');
      return;
    }
    await openPaths(picked);
  } catch (err) {
    toast(err.message, 'error');
    setStatus('打开失败');
  }
}

async function openDropped(input) {
  const paths = Array.isArray(input) ? input : (input ? [input] : []);
  if (!paths.length) return;
  await openPaths(paths);
}
window.easyexifOpenDropped = openDropped;

async function exportBundle() {
  if (!state.doc) return;
  if (state.doc.dirty) { toast('请先保存当前修改，再导出元数据包', 'info'); return; }
  try {
    const out = await api.chooseJsonSave(state.doc.name + '.metadata.json');
    if (!out) return;
    const res = await api.exportBundle(out);
    toast('已导出 ' + res.tags + ' 项元数据', 'success');
    setStatus('已导出元数据包', out);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function confirmReconstruct(info) {
  return new Promise(function (resolve) {
    const body = document.createElement('div');
    body.appendChild(el('p', 'modal-text', '此操作不会修改像素，但会覆盖当前文件的拍摄元数据，并写入 EasyExif 编辑标记。'));
    const source = info.source || {};
    const lines = [
      '来源：' + (source.file || '未知'),
      '相机：' + ([source.make, source.model].filter(Boolean).join(' ') || '未知'),
      '尺寸：' + (source.width || '?') + ' × ' + (source.height || '?'),
      '标记：' + (info.marker || 'EasyExif')
    ];
    lines.forEach(function (line) { body.appendChild(el('p', 'muted', line)); });
    body.appendChild(el('p', 'muted', '输出会另存为新文件，不会覆盖当前文件。'));
    modal({
      title: '元数据覆盖重建',
      body: body,
      actions: [
        { label: '取消', onClick: function () { resolve(false); } },
        { label: '继续', cls: 'primary', onClick: function () { resolve(true); } }
      ],
      onClose: function () { resolve(false); }
    });
  });
}

async function reconstructBundle() {
  const doc = state.doc;
  if (!doc) return;
  if (doc.readonly) { toast('RAW 文件当前为只读模式', 'info'); return; }
  if (doc.dirty) { toast('请先保存当前修改，再执行元数据覆盖重建', 'info'); return; }
  try {
    const bundlePath = await api.chooseJson();
    if (!bundlePath) return;
    const inspected = await api.inspectBundle(bundlePath);
    if (!(await confirmReconstruct(inspected.data))) return;
    const stem = doc.name.replace(/\.[^.]+$/, '');
    const out = await api.chooseSave(stem + '.reconstructed' + (doc.name.match(/\.[^.]+$/) || ['.jpg'])[0]);
    if (!out) return;
    setStatus('正在重建元数据…');
    const res = await api.reconstructBundle(bundlePath, out, 'replace');
    toast('已生成 ' + res.data.output, 'success');
    const opened = await api.open(res.data.output);
    if (opened.ok && opened.doc) setDoc(opened.doc);
  } catch (err) {
    toast(err.message, 'error');
    setStatus('重建失败');
  }
}

async function saveDoc(options) {
  if (!state.doc) return false;
  const force = !!(options && options.force);
  if (!force && !ensureEditable()) return false;
  const oldPath = state.doc.path;
  try {
    const res = await api.save();
    if (oldPath !== res.doc.path) delete state.reports[oldPath];
    setDoc(res.doc);
    toast('已保存到 ' + res.doc.path, 'success');
    setStatus('已保存', res.doc.path);
    return true;
  } catch (err) {
    toast(err.message, 'error');
    return false;
  }
}

function askClose() {
  return new Promise(function (resolve) {
    modal({
      title: '关闭文件',
      body: el('p', 'modal-text', '当前文件有未保存的修改。关闭前要保存吗？'),
      actions: [
        { label: '取消', onClick: function () { resolve('cancel'); } },
        { label: '不保存', cls: 'danger', onClick: function () { resolve('discard'); } },
        { label: '保存并关闭', cls: 'primary', onClick: function () { resolve('save'); } }
      ],
      onClose: function () { resolve('cancel'); }
    });
  });
}

async function closeDoc() {
  if (!state.doc) return;
  try {
    const fresh = await api.doc();
    if (fresh.doc && fresh.doc.open) setDoc(fresh.doc);
  } catch (e) { /* close with the local state */ }
  if (state.doc && state.doc.dirty) {
    const choice = await askClose();
    if (choice === 'cancel') return;
    if (choice === 'save') {
      const ok = await saveDoc({ force: true });
      if (!ok) return;
    }
  }
  const closingPath = state.doc ? state.doc.path : null;
  try {
    const res = await api.close();
    if (closingPath) delete state.reports[closingPath];
    setDoc(res.doc || { open: false });
    setStatus(res.doc && res.doc.open ? '已关闭，当前 ' + res.doc.name : '已关闭');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function undo() {
  if (!ensureEditable()) return;
  try {
    const res = await api.undo();
    delete state.reports[res.doc.path];
    setDoc(res.doc);
    if (state.tab === 'validate') showReportFor(res.doc);
    toast('已撤销', 'info');
  } catch (err) { toast(err.message, 'error'); }
}

async function redo() {
  if (!ensureEditable()) return;
  try {
    const res = await api.redo();
    delete state.reports[res.doc.path];
    setDoc(res.doc);
    if (state.tab === 'validate') showReportFor(res.doc);
    toast('已重做', 'info');
  } catch (err) { toast(err.message, 'error'); }
}

function bind() {
  $('#btnOpen').addEventListener('click', openDialog);
  $('#btnOpenLarge').addEventListener('click', openDialog);
  $('#btnEmptyOpen').addEventListener('click', openDialog);
  $('#btnSave').addEventListener('click', saveDoc);
  $('#btnExportBundle').addEventListener('click', exportBundle);
  $('#btnReconstruct').addEventListener('click', reconstructBundle);
  $('#btnClose').addEventListener('click', closeDoc);
  $('#btnUndo').addEventListener('click', undo);
  $('#btnRedo').addEventListener('click', redo);
  $('#btnValidate').addEventListener('click', runValidate);
  $('#btnRunValidate').addEventListener('click', runValidate);
  $('#btnBatch').addEventListener('click', openBatch);
  $('#btnTheme').addEventListener('click', toggleTheme);
  $('#modeSwitch').addEventListener('click', toggleMode);
  $('#btnAddTag').addEventListener('click', openAddTag);
  $('#btnDeleteTag').addEventListener('click', deleteSelected);
  $('#btnApplyXmp').addEventListener('click', applyXmp);
  $('#btnAddComment').addEventListener('click', addComment);
  $('#btnClearGps').addEventListener('click', clearGps);
  $('#gpsForm').addEventListener('submit', submitGps);

  $('#metaSearch').addEventListener('input', function (e) {
    state.filter = e.target.value || '';
    renderMeta();
  });
  $$('#metaScopes .scope').forEach(function (b) {
    b.addEventListener('click', function () {
      state.metaScope = b.dataset.scope;
      $$('#metaScopes .scope').forEach(function (x) { x.classList.toggle('active', x === b); });
      renderMeta();
    });
  });

  let dragDepth = 0;
  function hasFiles(e) {
    return !!(e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0);
  }
  document.addEventListener('dragenter', function (e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    document.body.classList.add('drop-active');
  });
  document.addEventListener('dragover', function (e) {
    if (hasFiles(e)) e.preventDefault();
  });
  document.addEventListener('dragleave', function (e) {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) document.body.classList.remove('drop-active');
  });
  document.addEventListener('drop', function (e) {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('drop-active');
  });
  $$('#viewTabs button').forEach(function (b) {
    b.addEventListener('click', function () { selectView(b.dataset.view); });
  });
  $$('#inspectorTabs button').forEach(function (b) {
    b.addEventListener('click', function () { selectTab(b.dataset.tab); });
  });
  $('#btnZoomIn').addEventListener('click', function () { state.fit = false; state.zoom = Math.min(5, state.zoom * 1.2); applyZoom(); });
  $('#btnZoomOut').addEventListener('click', function () { state.fit = false; state.zoom = Math.max(0.1, state.zoom / 1.2); applyZoom(); });
  $('#btnZoomFit').addEventListener('click', function () { state.fit = true; state.zoom = 1; applyZoom(); });

  $$('.quick').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!state.doc) return;
      if (b.dataset.quick === 'validate') {
        runValidate();
        return;
      }
      if (!ensureEditable()) return;
      if (b.dataset.quick === 'gps') selectTab('gps');
      if (b.dataset.quick === 'datetime') {
        applyOps([{ op: 'sync_datetime' }], '已同步拍摄时间');
      }
      if (b.dataset.quick === 'strip') {
        confirmDialog('清除元数据', '将删除 EXIF/XMP/IPTC/COM 等段，保留像素与 JFIF/DQT/SOF。此操作可撤销。').then(function (ok) {
          if (ok) applyOps([{ op: 'clear_metadata' }], '已清除元数据');
        });
      }
    });
  });

  document.addEventListener('keydown', function (e) {
    const mod = e.ctrlKey || e.metaKey;
    const target = e.target;
    const typing = !!(target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
      || target.isContentEditable));
    if (mod && e.key === 'Tab' && !typing && state.doc && state.doc.docs.length > 1) {
      e.preventDefault();
      cycleDoc();
      return;
    }
    if (mod && (e.key === '1' || e.key === '2') && !typing && state.doc) {
      const index = Number(e.key) - 1;
      if (index < state.doc.docs.length) {
        e.preventDefault();
        activateDoc(index);
        return;
      }
    }
    if (!typing && !mod && e.key.toLowerCase() === 'e') {
      e.preventDefault();
      toggleMode();
      return;
    }
    if (mod && e.key.toLowerCase() === 'o') { e.preventDefault(); openDialog(); }
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); saveDoc(); }
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); }
    if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); }
    if (e.key === 'F5') { e.preventDefault(); runValidate(); }
    if (e.key === 'Delete' && state.selected) deleteSelected();
  });
}

async function init() {
  const theme = localStorage.getItem('easyexif-theme') || 'light';
  document.documentElement.setAttribute('data-theme', theme);
  bind();
  setDoc(null);
  setStatus('就绪');
  try {
    const health = await api.health();
    if (health && health.version) {
      state.version = health.version;
      const badge = $('#appVersion');
      if (badge) badge.textContent = 'v' + health.version;
      renderTop();
    }
  } catch (err) { /* version badge keeps its static fallback */ }
  try {
    const res = await api.doc();
    if (res.doc && res.doc.open) setDoc(res.doc);
  } catch (err) {
    toast('无法连接本地服务：' + err.message, 'error');
  }
  setInterval(function () { api.heartbeat().catch(function () {}); }, 3000);
  api.heartbeat().catch(function () {});
}

init();
