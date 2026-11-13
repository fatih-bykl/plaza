// Denk sayfaları: tema düğmesi (ana siteyle aynı "theme" tercihi) ve ekran galerisi okları.
(function () {
  var root = document.documentElement;

  var toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      var light = root.className !== 'light';
      root.className = light ? 'light' : 'dark';
      var meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.setAttribute('content', light ? '#ffffff' : '#09090b');
      try {
        localStorage.setItem('theme', light ? 'light' : 'dark');
      } catch (e) {}
    });
  }

  var gallery = document.getElementById('gallery');
  if (gallery) {
    document.querySelectorAll('[data-scroll]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var dir = Number(btn.getAttribute('data-scroll'));
        gallery.scrollBy({ left: dir * gallery.clientWidth * 0.8, behavior: 'smooth' });
      });
    });
  }
})();
