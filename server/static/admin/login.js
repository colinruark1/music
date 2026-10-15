(function () {
  var form = document.getElementById('login-form');
  var status = document.getElementById('login-status');
  var button = form.querySelector('button');
  document.getElementById('username').focus();

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var username = form.username.value.trim();
    var password = form.password.value;
    if (!username || !password) {
      status.textContent = 'Enter your username and password.';
      return;
    }
    button.disabled = true;
    status.textContent = '';
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username, password: password })
    })
      .then(function (response) {
        return response.json().then(function (data) {
          if (response.ok) {
            window.location.replace('/admin');
            return;
          }
          status.textContent = data.error || 'Could not log in.';
          form.password.value = '';
          form.password.focus();
        });
      })
      .catch(function () {
        status.textContent = 'Could not reach the server. Is it still running?';
      })
      .then(function () {
        button.disabled = false;
      });
  });
})();
