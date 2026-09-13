// crudauth enforces a synchronizer token on unsafe requests: the session
// cookie is httpOnly, the CSRF cookie is not, and only the header counts.
// Served as a file rather than inlined so the Content-Security-Policy can
// refuse inline script entirely.
(function () {
  function csrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  document.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["X-CSRF-Token"] = csrfToken();
  });
})();
