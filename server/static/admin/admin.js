// Admin app: newsletter, music catalog and subscriber list.
// Everything user-supplied is put on the page with textContent, never innerHTML.

(function () {
  var state = { tracks: [], subscribers: [], campaigns: [], editing: null, pollTimer: null };

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

  var tabs = ['newsletter', 'music', 'subscribers'];

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
      if (data.mail.mode === 'outbox') {
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
        ? c.sent + ' of ' + c.recipients + ' so far'
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

    var sending = state.campaigns.some(function (c) { return c.status === 'sending'; });
    clearTimeout(state.pollTimer);
    if (sending) state.pollTimer = setTimeout(loadCampaigns, 2000);
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
          el('p', { class: 'small muted truncate', text: track.link })
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
    $('track-link').value = track.link;
    $('track-label').value = track.link_label;
    $('track-form-title').textContent = 'Edit track';
    $('track-save').textContent = 'Save changes';
    $('track-cancel').hidden = false;
    setStatus($('track-status'), '');
    showCoverPreview();
    $('track-title').focus();
  }

  function resetTrackForm() {
    state.editing = null;
    $('track-form').reset();
    $('track-form-title').textContent = 'Add a track';
    $('track-save').textContent = 'Add track';
    $('track-cancel').hidden = true;
    showCoverPreview();
  }

  function upload(fileInput, target, after) {
    var file = fileInput.files[0];
    if (!file) return;
    var status = $('track-status');
    setStatus(status, 'Uploading ' + file.name + '…');
    $('track-save').disabled = true;
    fetch('/api/admin/uploads?name=' + encodeURIComponent(file.name), {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file
    })
      .then(handle)
      .then(function (data) {
        target.value = data.url;
        setStatus(status, 'Uploaded ' + file.name + '.', 'ok');
        if (after) after();
      })
      .catch(function (error) { setStatus(status, error.message, 'error'); })
      .then(function () {
        fileInput.value = '';
        $('track-save').disabled = false;
      });
  }

  $('cover-file').addEventListener('change', function () { upload($('cover-file'), $('track-cover'), showCoverPreview); });
  $('audio-file').addEventListener('change', function () { upload($('audio-file'), $('track-link')); });
  $('track-cover').addEventListener('change', showCoverPreview);
  $('track-cancel').addEventListener('click', function () { resetTrackForm(); setStatus($('track-status'), ''); });

  $('track-form').addEventListener('submit', function (event) {
    event.preventDefault();
    var status = $('track-status');
    var track = {
      title: $('track-title').value.trim(),
      cover: $('track-cover').value.trim(),
      cover_alt: $('track-alt').value.trim(),
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
  Promise.all([loadSession(), loadTracks(), loadSubscribers(), loadCampaigns()]).catch(function (error) {
    setStatus($('compose-status'), error.message, 'error');
  });
})();
