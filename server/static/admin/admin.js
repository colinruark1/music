// Admin app: newsletter, music catalog and subscriber list.
// Everything user-supplied is put on the page with textContent, never innerHTML.

(function () {
  var state = { tracks: [], subscribers: [], campaigns: [], editing: null, sendingId: null };

  function $(id) { return document.getElementById(id); }

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (key) {
      if (key === 'text') node.textContent = props[key];
      else if (key === 'class') node.className = props[key];
      else if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), props[key]);
      else node.setAttribute(key, props[key]);
    });
    (children || []).forEach(function (child) { if (child) node.appendChild(child); });
    return node;
  }

  function api(method, path, body) {
    var options = { method: method, headers: {} };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    return fetch(path, options).then(handle);
  }

  function handle(response) {
    if (response.status === 401) {
      window.location.replace('/login');
      return new Promise(function () {});
    }
    return response.json().then(function (data) {
      if (!response.ok) throw new Error(data.error || 'Something went wrong.');
      return data;
    }, function () {
      throw new Error('The server sent back something unexpected.');
    });
  }

  function setStatus(node, text, kind) {
    node.textContent = text || '';
    node.className = 'status' + (kind ? ' ' + kind : '');
  }

  function formatDate(iso) {
    if (!iso) return '';
    var date = new Date(iso);
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) +
      ' · ' + date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  }

  // ---------- tabs ----------

  var tabs = ['newsletter', 'music', 'content', 'subscribers'];

  function showTab(name) {
    tabs.forEach(function (tab) {
      var selected = tab === name;
      $('tab-' + tab).setAttribute('aria-selected', String(selected));
      $('tab-' + tab).tabIndex = selected ? 0 : -1;
      $('panel-' + tab).hidden = !selected;
    });
    if (window.location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
  }

  tabs.forEach(function (tab, index) {
    var button = $('tab-' + tab);
    button.addEventListener('click', function () { showTab(tab); });
    button.addEventListener('keydown', function (event) {
      var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      var next = tabs[(index + step + tabs.length) % tabs.length];
      showTab(next);
      $('tab-' + next).focus();
    });
  });

  // ---------- session ----------

  $('logout').addEventListener('click', function () {
    api('POST', '/api/logout', {}).then(function () { window.location.replace('/login'); });
  });

  function loadSession() {
    return api('GET', '/api/admin/session').then(function (data) {
      $('who').textContent = 'Signed in as ' + data.username;
      var notice = $('mail-notice');
      notice.textContent = '';
      if (data.mail.mode === 'off') {
        notice.appendChild(el('strong', { text: 'Email isn’t connected yet. ' }));
        notice.appendChild(document.createTextNode(
          'Add your email provider’s SMTP settings to the Vercel project (see the README) to send letters.'));
        notice.hidden = false;
      } else if (data.mail.mode === 'outbox') {
        notice.appendChild(el('strong', { text: 'Email isn’t connected yet. ' }));
        notice.appendChild(document.createTextNode(
          'Letters are saved as files in ' + data.mail.outbox + ' instead of being sent. ' +
          'Set SMTP_HOST and the other SMTP_ settings (see the README) to send for real.'));
        notice.hidden = false;
      } else if (/127\.0\.0\.1|localhost/.test(data.mail.site_url)) {
        notice.appendChild(el('strong', { text: 'Heads up: ' }));
        notice.appendChild(document.createTextNode(
          'SITE_URL is ' + data.mail.site_url + ', so links and cover art in emails will only work on this computer.'));
        notice.hidden = false;
      }
    });
  }

  // ---------- newsletter ----------

  function renderFeatureOptions() {
    var select = $('feature');
    var current = select.value;
    select.textContent = '';
    select.appendChild(el('option', { value: '', text: 'None' }));
    state.tracks.forEach(function (track) {
      select.appendChild(el('option', { value: track.id, text: track.title }));
    });
    select.value = state.tracks.some(function (t) { return t.id === current; }) ? current : '';
  }

  function renderSubscriberCount() {
    var count = state.subscribers.length;
    $('subscriber-count').textContent = String(count);
    $('send-all').textContent = count === 1 ? 'Send to 1 subscriber' : 'Send to ' + count + ' subscribers';
    $('send-all').disabled = count === 0 || state.campaigns.some(function (c) { return c.status === 'sending'; });
  }

  function renderCampaigns() {
    var list = $('campaigns');
    list.textContent = '';
    if (!state.campaigns.length) {
      list.appendChild(el('li', { class: 'empty', text: 'Nothing sent yet.' }));
    }
    state.campaigns.forEach(function (c) {
      var progress = c.status === 'sending'
        ? c.sent + ' of ' + c.recipients + ' so far. Keep this page open until it finishes.'
        : c.sent + ' of ' + c.recipients + ' delivered' + (c.failed ? ', ' + c.failed + ' failed' : '');
      if (c.mode === 'outbox') progress += ' (saved to outbox)';
      var meta = el('p', { class: 'campaign-meta', text: formatDate(c.created_at) + ' · ' + c.sent_by });
      var details = el('div', { class: 'grow' }, [
        el('div', { class: 'truncate', text: c.subject }),
        meta,
        el('p', { class: 'campaign-meta', text: progress }),
        c.track_title ? el('p', { class: 'campaign-meta', text: 'Featured: ' + c.track_title }) : null
      ]);
      if (c.errors && c.errors.length) {
        details.appendChild(el('details', { class: 'campaign-meta' }, [
          el('summary', { text: 'Show errors' }),
          el('pre', { class: 'small', text: c.errors.join('\n') })
        ]));
      }
      list.appendChild(el('li', {}, [
        details,
        el('span', { class: 'pill ' + c.status, text: c.status })
      ]));
    });
    renderSubscriberCount();

    var sending = state.campaigns.filter(function (c) { return c.status === 'sending'; })[0];
    if (sending) sendNextBatch(sending.id);
  }

  // Sends go out a batch at a time while this page is open. If it's closed
  // part-way, the send carries on from where it stopped the next time an
  // admin opens this page.
  function sendNextBatch(id) {
    if (state.sendingId) return;
    state.sendingId = id;
    api('POST', '/api/admin/campaigns/' + encodeURIComponent(id) + '/send', {})
      .then(function (data) {
        state.campaigns = state.campaigns.map(function (c) { return c.id === id ? data.campaign : c; });
      })
      .catch(function (error) {
        setStatus($('compose-status'), error.message + ' Retrying in 10 seconds…', 'error');
        return new Promise(function (resolve) { setTimeout(resolve, 10000); });
      })
      .then(function () {
        state.sendingId = null;
        renderCampaigns();
      });
  }

  function loadCampaigns() {
    return api('GET', '/api/admin/campaigns').then(function (data) {
      state.campaigns = data.campaigns;
      renderCampaigns();
    });
  }

  function letter() {
    return {
      subject: $('subject').value.trim(),
      body: $('body').value,
      track_id: $('feature').value || null
    };
  }

  function checkLetter(status) {
    var draft = letter();
    if (!draft.subject) { setStatus(status, 'Write a subject first.', 'error'); $('subject').focus(); return null; }
    if (!draft.body.trim()) { setStatus(status, 'Write the message first.', 'error'); $('body').focus(); return null; }
    return draft;
  }

  $('send-test').addEventListener('click', function () {
    var status = $('compose-status');
    var draft = checkLetter(status);
    if (!draft) return;
    draft.to = $('test-to').value.trim();
    if (!draft.to) { setStatus(status, 'Enter an address to send the test to.', 'error'); $('test-to').focus(); return; }
    var button = $('send-test');
    button.disabled = true;
    setStatus(status, 'Sending test…');
    api('POST', '/api/admin/campaigns/test', draft)
      .then(function (data) { setStatus(status, data.message, 'ok'); })
      .catch(function (error) { setStatus(status, error.message, 'error'); })
      .then(function () { button.disabled = false; });
  });

  $('compose').addEventListener('submit', function (event) {
    event.preventDefault();
    var status = $('compose-status');
    var draft = checkLetter(status);
    if (!draft) return;
    var count = state.subscribers.length;
    if (!window.confirm('Send “' + draft.subject + '” to ' + count + (count === 1 ? ' person' : ' people') + '? This can’t be undone.')) return;
    $('send-all').disabled = true;
    setStatus(status, 'Starting…');
    api('POST', '/api/admin/campaigns', draft)
      .then(function () {
        setStatus(status, 'Sending. Progress shows under Sent.', 'ok');
        $('subject').value = '';
        $('body').value = '';
        $('feature').value = '';
        return loadCampaigns();
      })
      .catch(function (error) {
        setStatus(status, error.message, 'error');
        renderSubscriberCount();
      });
  });

  // ---------- music ----------

  function renderTracks() {
    var list = $('tracks');
    list.textContent = '';
    if (!state.tracks.length) {
      list.appendChild(el('li', { class: 'empty', text: 'No tracks yet. Add one with the form.' }));
    }
    state.tracks.forEach(function (track, index) {
      var cover = el('img', { class: 'track-cover', src: track.cover, alt: '' });
      list.appendChild(el('li', {}, [
        cover,
        el('div', { class: 'grow' }, [
          el('h3', { class: 'truncate', text: track.title }),
          el('p', { class: 'small muted truncate', text: trackSummary(track) })
        ]),
        el('div', { class: 'actions' }, [
          el('button', { class: 'secondary small', type: 'button', 'aria-label': 'Move ' + track.title + ' up',
            text: '↑', onclick: function () { moveTrack(track, 'up'); } }),
          el('button', { class: 'secondary small', type: 'button', 'aria-label': 'Move ' + track.title + ' down',
            text: '↓', onclick: function () { moveTrack(track, 'down'); } }),
          el('button', { class: 'secondary small', type: 'button', text: 'Edit',
            onclick: function () { editTrack(track); } }),
          el('button', { class: 'danger small', type: 'button', text: 'Delete',
            onclick: function () { deleteTrack(track); } })
        ])
      ]));
      if (index === 0) cover.setAttribute('loading', 'eager');
    });
    renderFeatureOptions();
  }

  function trackSummary(track) {
    var parts = [];
    if (track.audio) parts.push('▶ Plays on the site');
    if (track.link) parts.push(track.link);
    return parts.join(' · ');
  }

  function showAudio() {
    var url = $('track-audio').value;
    $('audio-name').textContent = url ? '▶ ' + decodeURIComponent(url.split('/').pop()) : 'No audio yet.';
    $('audio-remove').hidden = !url;
  }

  function loadTracks() {
    return api('GET', '/api/admin/tracks').then(function (data) {
      state.tracks = data.tracks;
      renderTracks();
    });
  }

  function moveTrack(track, direction) {
    api('POST', '/api/admin/tracks/' + encodeURIComponent(track.id) + '/move', { direction: direction })
      .then(loadTracks)
      .catch(function (error) { setStatus($('track-status'), error.message, 'error'); });
  }

  function deleteTrack(track) {
    if (!window.confirm('Take “' + track.title + '” off the site?')) return;
    api('DELETE', '/api/admin/tracks/' + encodeURIComponent(track.id), {})
      .then(function () {
        if (state.editing === track.id) resetTrackForm();
        setStatus($('track-status'), 'Removed “' + track.title + '”.', 'ok');
        return loadTracks();
      })
      .catch(function (error) { setStatus($('track-status'), error.message, 'error'); });
  }

  function showCoverPreview() {
    var url = $('track-cover').value.trim();
    var preview = $('cover-preview');
    preview.hidden = !url;
    if (url) preview.src = url;
  }

  function editTrack(track) {
    state.editing = track.id;
    $('track-title').value = track.title;
    $('track-cover').value = track.cover;
    $('track-alt').value = track.cover_alt;
    $('track-audio').value = track.audio || '';
    $('track-link').value = track.link;
    $('track-label').value = track.link_label;
    $('track-form-title').textContent = 'Edit track';
    $('track-save').textContent = 'Save changes';
    $('track-cancel').hidden = false;
    setStatus($('track-status'), '');
    showCoverPreview();
    showAudio();
    $('track-title').focus();
  }

  function resetTrackForm() {
    state.editing = null;
    $('track-form').reset();
    $('track-audio').value = '';
    $('track-form-title').textContent = 'Add a track';
    $('track-save').textContent = 'Add track';
    $('track-cancel').hidden = true;
    showCoverPreview();
    showAudio();
  }

  // Phone photos are often stored sideways with a flag saying "turn me".
  // Browsers obey it, but link previews and some email apps don't, so each
  // photo is redrawn upright (and at most 2400px) before it's uploaded. That
  // also drops hidden photo data, like where it was taken.
  var MAX_PHOTO_SIDE = 2400;

  function prepareImage(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || !window.createImageBitmap) return Promise.resolve(file);
    return createImageBitmap(file, { imageOrientation: 'from-image' }).then(function (bitmap) {
      var scale = Math.min(1, MAX_PHOTO_SIDE / Math.max(bitmap.width, bitmap.height));
      var canvas = document.createElement('canvas');
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      var type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
      return new Promise(function (resolve) {
        canvas.toBlob(function (blob) {
          if (!blob) return resolve(file);
          var name = file.name.replace(/\.[^.]*$/, '') + (type === 'image/png' ? '.png' : '.jpg');
          resolve(new File([blob], name, { type: type }));
        }, type, 0.9);
      });
    }).catch(function () { return file; });
  }

  function upload(fileInput, target, after, status, saveButton) {
    var picked = fileInput.files[0];
    if (!picked) return;
    status = status || $('track-status');
    saveButton = saveButton || $('track-save');
    setStatus(status, 'Uploading ' + picked.name + '…');
    saveButton.disabled = true;
    // The server hands out a one-time upload URL; the file goes straight to
    // Supabase Storage, so large audio files never pass through the server.
    var publicUrl, file;
    prepareImage(picked)
      .then(function (prepared) {
        file = prepared;
        return api('POST', '/api/admin/uploads', { name: file.name, size: file.size });
      })
      .then(function (data) {
        publicUrl = data.url;
        return fetch(data.upload_url, {
          method: 'PUT',
          headers: { 'Content-Type': file.type || 'application/octet-stream' },
          body: file
        });
      })
      .then(function (response) {
        if (response.ok) return;
        return response.json().catch(function () { return {}; }).then(function (data) {
          throw new Error('Upload failed: ' + (data.message || data.error || response.status));
        });
      })
      .then(function () {
        target.value = publicUrl;
        setStatus(status, 'Uploaded ' + picked.name + '.', 'ok');
        if (after) after();
      })
      .catch(function (error) { setStatus(status, error.message, 'error'); })
      .then(function () {
        fileInput.value = '';
        saveButton.disabled = false;
      });
  }

  $('cover-file').addEventListener('change', function () { upload($('cover-file'), $('track-cover'), showCoverPreview); });
  $('audio-file').addEventListener('change', function () { upload($('audio-file'), $('track-audio'), showAudio); });
  $('audio-remove').addEventListener('click', function () { $('track-audio').value = ''; showAudio(); });
  showAudio();
  $('track-cover').addEventListener('change', showCoverPreview);
  $('track-cancel').addEventListener('click', function () { resetTrackForm(); setStatus($('track-status'), ''); });

  $('track-form').addEventListener('submit', function (event) {
    event.preventDefault();
    var status = $('track-status');
    var track = {
      title: $('track-title').value.trim(),
      cover: $('track-cover').value.trim(),
      cover_alt: $('track-alt').value.trim(),
      audio: $('track-audio').value.trim(),
      link: $('track-link').value.trim(),
      link_label: $('track-label').value.trim()
    };
    var editing = state.editing;
    $('track-save').disabled = true;
    var request = editing
      ? api('PUT', '/api/admin/tracks/' + encodeURIComponent(editing), track)
      : api('POST', '/api/admin/tracks', track);
    request
      .then(function () {
        resetTrackForm();
        setStatus(status, editing ? 'Saved “' + track.title + '”.' : 'Added “' + track.title + '” to the top of the list.', 'ok');
        return loadTracks();
      })
      .catch(function (error) { setStatus(status, error.message, 'error'); })
      .then(function () { $('track-save').disabled = false; });
  });

  // ---------- home page ----------

  // The server describes each section's fields (see server/content.py), and
  // the forms are built from that, so a new field only needs adding there.

  var fieldCount = 0;

  function fieldId() { fieldCount += 1; return 'content-field-' + fieldCount; }

  function hintFor(spec) {
    return spec.hint ? el('p', { class: 'hint', text: spec.hint }) : null;
  }

  // One input. Returns { node, read } where read() gives its current value.
  function buildField(spec, value, status, saveButton) {
    var id = fieldId();
    var input;
    if (spec.kind === 'text' && spec.max >= 300) {
      input = el('textarea', { id: id, maxlength: String(spec.max), rows: '3' });
    } else {
      input = el('input', { id: id, type: spec.kind === 'email' ? 'email' : 'text', maxlength: String(spec.max) });
    }
    input.value = value || '';
    if (spec.kind !== 'image') {
      return {
        node: el('div', { class: 'field' }, [el('label', { for: id, text: spec.label }), input, hintFor(spec)]),
        read: function () { return input.value.trim(); }
      };
    }
    var preview = el('img', { class: 'photo-preview', alt: '' });
    function showPreview() {
      preview.hidden = !input.value.trim();
      if (input.value.trim()) preview.src = input.value.trim();
    }
    var file = el('input', { type: 'file', accept: 'image/jpeg,image/png,image/webp', 'aria-label': 'Upload ' + spec.label.toLowerCase() });
    file.addEventListener('change', function () { upload(file, input, showPreview, status, saveButton); });
    input.addEventListener('change', showPreview);
    input.setAttribute('placeholder', 'https://… (or upload above)');
    showPreview();
    return {
      node: el('div', { class: 'field' }, [
        el('label', { for: id, text: spec.label }), preview,
        el('div', { class: 'upload-row' }, [file]), input, hintFor(spec)
      ]),
      read: function () { return input.value.trim(); }
    };
  }

  // A list (show dates, about facts): rows that can be added, moved, removed.
  function buildList(spec, items) {
    var rows = [];
    var holder = el('div', { class: 'list-items' });
    var addButton = el('button', { class: 'secondary small', type: 'button', text: 'Add' });

    function render() {
      holder.textContent = '';
      if (!rows.length) holder.appendChild(el('p', { class: 'muted small', text: 'None yet.' }));
      rows.forEach(function (row, index) {
        holder.appendChild(el('div', { class: 'list-item' }, [
          el('div', { class: 'list-item-head' }, [
            el('strong', { text: spec.label.replace(/s$/, '') + ' ' + (index + 1) }),
            el('div', { class: 'actions' }, [
              el('button', { class: 'secondary small', type: 'button', text: '↑', 'aria-label': 'Move up',
                onclick: function () { move(index, -1); } }),
              el('button', { class: 'secondary small', type: 'button', text: '↓', 'aria-label': 'Move down',
                onclick: function () { move(index, 1); } }),
              el('button', { class: 'danger small', type: 'button', text: 'Remove',
                onclick: function () { rows.splice(index, 1); render(); } })
            ])
          ]),
          el('div', { class: 'row' }, row.fields.map(function (f) { return f.node; }))
        ]));
      });
      addButton.disabled = rows.length >= spec.max;
    }

    function addRow(item) {
      rows.push({ fields: spec.fields.map(function (sub) {
        var built = buildField(sub, item[sub.name]);
        built.name = sub.name;
        return built;
      }) });
    }

    function move(index, step) {
      var target = index + step;
      if (target < 0 || target >= rows.length) return;
      rows.splice(target, 0, rows.splice(index, 1)[0]);
      render();
    }

    addButton.addEventListener('click', function () { addRow({}); render(); });
    (items || []).forEach(addRow);
    render();

    return {
      node: el('div', { class: 'field' }, [el('span', { class: 'label', text: spec.label }), holder,
        el('div', { class: 'row' }, [addButton])]),
      read: function () {
        return rows.map(function (row) {
          var item = {};
          row.fields.forEach(function (f) { item[f.name] = f.read(); });
          return item;
        });
      }
    };
  }

  function buildSection(section) {
    var status = el('p', { class: 'status', role: 'status' });
    var save = el('button', { type: 'submit', text: 'Save' });
    var reset = el('button', { class: 'secondary', type: 'button', text: 'Back to the design’s text', hidden: '' });
    if (section.saved) reset.hidden = false;
    var fields = section.fields.map(function (spec) {
      var built = spec.kind === 'list'
        ? buildList(spec, section.value[spec.name])
        : buildField(spec, section.value[spec.name], status, save);
      built.name = spec.name;
      return built;
    });
    var form = el('form', { class: 'card content-section', novalidate: '' }, [
      el('h2', { text: section.title })
    ].concat(fields.map(function (f) { return f.node; })).concat([
      el('div', { class: 'row' }, [save, reset]), status
    ]));

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var value = {};
      fields.forEach(function (f) { value[f.name] = f.read(); });
      save.disabled = true;
      setStatus(status, 'Saving…');
      api('PUT', '/api/admin/content/' + section.name, value)
        .then(function () {
          setStatus(status, 'Saved. It’s live on the site now.', 'ok');
          reset.hidden = false;
        })
        .catch(function (error) { setStatus(status, error.message, 'error'); })
        .then(function () { save.disabled = false; });
    });

    reset.addEventListener('click', function () {
      if (!window.confirm('Put “' + section.title + '” back to the text from the design? Your saved changes to it will be lost.')) return;
      api('DELETE', '/api/admin/content/' + section.name, {})
        .then(loadContent)
        .catch(function (error) { setStatus(status, error.message, 'error'); });
    });
    return form;
  }

  function loadContent() {
    return api('GET', '/api/admin/content').then(function (data) {
      var holder = $('content-sections');
      holder.textContent = '';
      data.sections.forEach(function (section) { holder.appendChild(buildSection(section)); });
    }).catch(function (error) {
      setStatus($('content-status'), error.message, 'error');
    });
  }

  // ---------- subscribers ----------

  function renderSubscribers() {
    var list = $('subscribers');
    var query = $('subscriber-search').value.trim().toLowerCase();
    list.textContent = '';
    var shown = state.subscribers
      .slice()
      .reverse()
      .filter(function (s) { return !query || s.email.toLowerCase().indexOf(query) !== -1; });
    if (!shown.length) {
      list.appendChild(el('li', { class: 'empty', text: query ? 'No matches.' : 'Nobody has signed up yet.' }));
    }
    shown.forEach(function (s) {
      list.appendChild(el('li', {}, [
        el('div', { class: 'grow' }, [
          el('div', { class: 'truncate', text: s.email }),
          el('p', { class: 'small muted', text: 'Joined ' + formatDate(s.subscribed_at) })
        ]),
        el('div', { class: 'actions' }, [
          el('button', { class: 'danger small', type: 'button', text: 'Remove',
            onclick: function () { removeSubscriber(s.email); } })
        ])
      ]));
    });
    renderSubscriberCount();
  }

  function loadSubscribers() {
    return api('GET', '/api/admin/subscribers').then(function (data) {
      state.subscribers = data.subscribers;
      renderSubscribers();
    });
  }

  function removeSubscriber(email) {
    if (!window.confirm('Remove ' + email + ' from the list?')) return;
    api('DELETE', '/api/admin/subscribers', { email: email })
      .then(loadSubscribers)
      .catch(function (error) { window.alert(error.message); });
  }

  $('subscriber-search').addEventListener('input', renderSubscribers);

  // ---------- start ----------

  var initial = window.location.hash.slice(1);
  showTab(tabs.indexOf(initial) !== -1 ? initial : 'newsletter');
  loadContent();
  Promise.all([loadSession(), loadTracks(), loadSubscribers(), loadCampaigns()]).catch(function (error) {
    setStatus($('compose-status'), error.message, 'error');
  });
})();
