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
