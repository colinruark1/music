// Behaviour the design files don't carry on their own. The server appends
// this script to every page it renders.

(function () {
  var input = document.getElementById('letters-email');
  var form = input && input.closest('form');
  if (!form) return;

  var button = form.querySelector('button');
  var status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.style.margin = '4px 0 0';
  status.style.minHeight = '1.55em';
  form.appendChild(status);

  function subscribe(event) {
    event.preventDefault();
    var email = input.value.trim();
    if (!email) {
      status.textContent = 'Enter your email address first.';
      input.focus();
      return;
    }
    button.disabled = true;
    status.textContent = 'Signing you up…';
    fetch('/api/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email })
    })
      .then(function (response) {
        return response.json().then(function (data) {
          status.textContent = data.message || data.error || 'Something went wrong.';
          if (response.ok) input.value = '';
        });
      })
      .catch(function () {
        status.textContent = 'Could not reach the server. Is it still running?';
      })
      .then(function () {
        button.disabled = false;
      });
  }

  form.addEventListener('submit', subscribe);
  if (button) button.addEventListener('click', subscribe);
})();

// Music cards: songs play on the page through one shared player, so starting
// one pauses the last. The audio element is never put in the page, so there
// are no browser controls or "Save audio as" menu, and no download link.
(function () {
  var buttons = document.querySelectorAll('button[data-audio]');
  if (!buttons.length) return;

  var audio = new Audio();
  audio.preload = 'none';
  var current = null;

  function part(button, selector) {
    return button.closest('article').querySelector(selector);
  }

  function title(button) {
    return button.getAttribute('aria-label').replace(/^(Play|Pause) /, '');
  }

  function clock(seconds) {
    if (!isFinite(seconds)) return '0:00';
    seconds = Math.floor(seconds);
    return Math.floor(seconds / 60) + ':' + ('0' + (seconds % 60)).slice(-2);
  }

  function showPlaying(button, playing) {
    button.querySelector('[data-icon="play"]').style.display = playing ? 'none' : '';
    button.querySelector('[data-icon="pause"]').style.display = playing ? '' : 'none';
    button.setAttribute('aria-label', (playing ? 'Pause ' : 'Play ') + title(button));
  }

  function showTime() {
    if (!current) return;
    var seek = part(current, '[data-seek]');
    if (audio.duration) seek.value = Math.round((audio.currentTime / audio.duration) * 1000);
    part(current, '[data-time]').textContent = audio.duration
      ? clock(audio.currentTime) + ' / ' + clock(audio.duration)
      : clock(audio.currentTime);
  }

  function reset(button) {
    showPlaying(button, false);
    var seek = part(button, '[data-seek]');
    seek.value = 0;
    seek.disabled = true;
    part(button, '[data-time]').textContent = '0:00';
  }

  function play() {
    var started = audio.play();
    if (started && started.catch) {
      started.catch(function (error) {
        if (error.name !== 'AbortError' && current) {
          showPlaying(current, false);
          part(current, '[data-time]').textContent = 'Couldn’t play';
        }
      });
    }
  }

  Array.prototype.forEach.call(buttons, function (button) {
    button.addEventListener('click', function () {
      if (button !== current) {
        if (current) reset(current);
        current = button;
        audio.src = button.getAttribute('data-audio');
        play();
      } else if (audio.paused) {
        play();
      } else {
        audio.pause();
      }
    });

    part(button, '[data-seek]').addEventListener('input', function (event) {
      if (button === current && audio.duration) {
        audio.currentTime = (event.target.value / 1000) * audio.duration;
      }
    });
  });

  audio.addEventListener('play', function () { if (current) showPlaying(current, true); });
  audio.addEventListener('pause', function () { if (current) showPlaying(current, false); });
  audio.addEventListener('loadedmetadata', function () {
    if (current) part(current, '[data-seek]').disabled = false;
    showTime();
  });
  audio.addEventListener('timeupdate', showTime);
  audio.addEventListener('ended', function () {
    audio.currentTime = 0;
    showTime();
  });
  audio.addEventListener('error', function () {
    if (!current || !audio.src) return;
    showPlaying(current, false);
    part(current, '[data-time]').textContent = 'Couldn’t play';
  });
})();
