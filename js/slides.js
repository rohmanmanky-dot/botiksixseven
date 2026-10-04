(function () {
  const SITE_URL = "https://rohmanmanky-dot.github.io/botiksixseven/";
  const COMMONS = "https://commons.wikimedia.org/wiki/Special:FilePath/";
  const byId = Object.fromEntries(window.STOPS.map((s, i) => [s.id, { ...s, num: i + 1 }]));

  // ---------- Слайды остановок из js/stops.js ----------

  document.querySelectorAll(".slide--stop").forEach((el) => {
    const s = byId[el.dataset.stop];
    const bullets = el.dataset.bullets.split("|");
    const fallback = s.commons ? `data-fallback="${s.commons}"` : "";
    el.innerHTML = `
      <div class="split">
        <figure class="photo">
          <img src="images/${s.photo}" alt="${s.title}" ${fallback} onerror="slidePhotoFail(this)">
          <figcaption>images/${s.photo}</figcaption>
        </figure>
        <div class="pad">
          <p class="kicker">Остановка ${s.num} из ${window.STOPS.length} · ${s.place}</p>
          <h2>${s.title}</h2>
          <ul class="bullets">${bullets.map((b) => `<li>${b}</li>`).join("")}</ul>
          <p class="howto">${el.dataset.howto}</p>
        </div>
      </div>
      <aside class="notes">${s.text.replace(/<p class="draft">.*?<\/p>/s, "")}</aside>`;
  });

  window.slidePhotoFail = function (img) {
    const fb = img.dataset.fallback;
    if (fb && img.src.indexOf("commons.wikimedia.org") === -1) {
      img.src = COMMONS + encodeURIComponent(fb) + "?width=1600";
      return;
    }
    img.parentElement.classList.add("photo--empty");
    img.remove();
  };

  // ---------- Источники ----------

  const groups = [
    ["О Чечне и маршруте", [
      ["Кавказ.РФ: маршрут по Аргунскому ущелью", "https://kavkaz.travel/en/touristRoutes/32"],
      ["Школьный туризм России: маршрут", "https://школьныйтуризмроссии.рф/routes/detail/?ELEMENT_ID=1116"],
      ["argmz.ru: экскурсия в Цой-Педе", "https://argmz.ru/экскурсия-в-цой-педе/"],
    ]],
    ...["mosque", "nikhaloy", "ushkaloy", "tsoi-pede"].map((id) => [byId[id].title, byId[id].sources]),
    ["Монета", window.FINALE.sources],
    ["Остановки по пути", window.STOPS.filter((s) => s.kind === "way").flatMap((s) => s.sources)],
    ["Фото и карта", [
      ["Wikimedia Commons (фото, лицензии CC)", "https://commons.wikimedia.org/wiki/Category:Chechnya"],
      ["© участники OpenStreetMap (карта)", "https://www.openstreetmap.org/copyright"],
    ]],
  ];
  const host = (u) => u.split("/")[2].replace(/^www\./, "");
  document.getElementById("sources-grid").innerHTML = groups
    .map(([name, list]) => `
      <div class="src-group">
        <h3>${name}</h3>
        <ul>${list.map(([t, u]) => `<li><a href="${u}" target="_blank" rel="noopener">${t}</a> <span>${host(u)}</span></li>`).join("")}</ul>
      </div>`)
    .join("");

  // ---------- QR на сайт ----------

  document.getElementById("site-url").textContent = SITE_URL.replace("https://", "");
  if (window.QRCode) {
    new QRCode(document.getElementById("qr"), { text: SITE_URL, width: 512, height: 512, colorDark: "#08392b" });
  }

  // ---------- Карты ----------

  const maps = {};
  const tiles = () => L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  });

  function regionMap() {
    const m = L.map("map-region", { zoomControl: false, attributionControl: true }).setView([43.2, 45.7], 6);
    tiles().addTo(m);
    const icon = L.divIcon({ className: "", html: '<div class="pin pin--main">★</div>', iconSize: [34, 34], iconAnchor: [17, 17] });
    L.marker([43.3176, 45.6939], { icon }).addTo(m).bindTooltip("Грозный", { permanent: true, direction: "right", offset: [16, 0] });
    return m;
  }

  function routeMap() {
    const m = L.map("map-route", { scrollWheelZoom: true });
    tiles().addTo(m);
    const pts = window.STOPS.map((s) => s.coords);
    window.STOPS.forEach((s, i) => {
      const icon = L.divIcon({ className: "", html: `<div class="pin pin--${s.kind}">${i + 1}</div>`, iconSize: [34, 34], iconAnchor: [17, 17] });
      L.marker(s.coords, { icon, zIndexOffset: s.kind === "main" ? 1000 : 0 })
        .addTo(m)
        .bindPopup(`<b>${i + 1}. ${s.title}</b><br>${s.place}<br>${s.facts.join(" · ")}`);
    });
    m.fitBounds(pts, { padding: [30, 30] });

    const info = document.getElementById("route-info");
    const coordStr = pts.map(([lat, lon]) => `${lon},${lat}`).join(";");
    fetch(`https://router.project-osrm.org/route/v1/driving/${coordStr}?overview=full&geometries=geojson`)
      .then((r) => r.json())
      .then((d) => {
        if (d.code !== "Ok") throw new Error(d.code);
        L.geoJSON(d.routes[0].geometry, { style: { color: "#0b6e4f", weight: 5, opacity: 0.85 } }).addTo(m);
        info.textContent = `Весь маршрут ≈ ${Math.round(d.routes[0].distance / 1000)} км по дорогам`;
      })
      .catch(() => {
        L.polyline(pts, { color: "#0b6e4f", weight: 3, dashArray: "6 8" }).addTo(m);
        info.textContent = "Пунктир — схема, не точная дорога";
      });
    return m;
  }

  function ensureMap(slide) {
    if (!window.L) return;
    const el = slide.querySelector(".map");
    if (!el) return;
    if (!maps[el.id]) maps[el.id] = el.id === "map-route" ? routeMap() : regionMap();
    setTimeout(() => maps[el.id].invalidateSize(), 50);
  }

  // ---------- Навигация ----------

  const slides = [...document.querySelectorAll(".slide")];
  const counter = document.getElementById("counter");
  const speaker = document.getElementById("speaker");
  let cur = 0;

  function show(i) {
    cur = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, k) => s.classList.toggle("is-active", k === cur));
    counter.textContent = `${cur + 1} / ${slides.length}`;
    const who = slides[cur].dataset.speaker;
    speaker.textContent = who && who !== "—" ? `Говорит: ${who}` : "";
    history.replaceState(null, "", `#${cur + 1}`);
    ensureMap(slides[cur]);
  }

  document.getElementById("prev").onclick = () => show(cur - 1);
  document.getElementById("next").onclick = () => show(cur + 1);
  document.getElementById("fs").onclick = () =>
    document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();

  document.addEventListener("keydown", (e) => {
    if (["ArrowRight", "PageDown", " ", "Enter"].includes(e.key)) { e.preventDefault(); show(cur + 1); }
    else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); show(cur - 1); }
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(slides.length - 1);
    else if (e.key === "f" || e.key === "а") document.getElementById("fs").click();
    else if (e.key === "n" || e.key === "т") document.body.classList.toggle("show-notes");
  });

  // Свайпы на телефоне/планшете (кроме карты — там свайп двигает карту)
  let x0 = null;
  document.addEventListener("touchstart", (e) => { x0 = e.target.closest(".map") ? null : e.touches[0].clientX; });
  document.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50) show(cur + (dx < 0 ? 1 : -1));
  });

  window.addEventListener("beforeprint", () => slides.forEach(ensureMap));
  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
})();
