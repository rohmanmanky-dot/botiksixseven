(function () {
  const stops = window.STOPS;

  // ---------- Карточки остановок ----------

  function photo(file, alt) {
    // Если картинки ещё нет в images/, показываем аккуратную заглушку.
    return `
      <figure class="photo">
        <img src="images/${file}" alt="${alt}" loading="lazy"
             onerror="this.parentElement.classList.add('photo--empty'); this.remove();">
        <figcaption>Фото: images/${file}</figcaption>
      </figure>`;
  }

  function sources(list) {
    return `
      <details class="sources">
        <summary>Источники</summary>
        <ul>${list.map(([name, url]) => `<li><a href="${url}" target="_blank" rel="noopener">${name}</a></li>`).join("")}</ul>
      </details>`;
  }

  function facts(list) {
    return `<ul class="facts">${list.map((f) => `<li>${f}</li>`).join("")}</ul>`;
  }

  document.getElementById("stops-list").innerHTML = stops
    .map((s, i) => `
      <article class="stop stop--${s.kind}" id="stop-${s.id}">
        ${photo(s.photo, s.title)}
        <div class="stop__body">
          <p class="stop__meta">
            <span class="stop__num">${i + 1}</span>
            ${s.kind === "main" ? "Главная точка" : "По пути"}
            ${s.kind === "main" ? `<span class="tag">${s.author}</span>` : ""}
          </p>
          <h3>${s.title}</h3>
          <p class="stop__place">${s.place}</p>
          ${facts(s.facts)}
          <div class="stop__text">${s.text}</div>
          <h4>Как добраться</h4>
          <div class="stop__howto">${s.howto}</div>
          ${sources(s.sources)}
        </div>
      </article>`)
    .join("");

  const f = window.FINALE;
  document.getElementById("finale").innerHTML = `
    <h2>${f.title}</h2>
    <div class="finale__grid">
      ${photo(f.photo, "Монета 10 рублей 2010 года «Чеченская Республика»")}
      <div>
        ${facts(f.facts)}
        ${f.text}
        ${sources(f.sources)}
      </div>
    </div>`;

  // ---------- Карта ----------

  if (!window.L) return; // нет интернета — карточки всё равно видны

  const map = L.map("route-map", { scrollWheelZoom: false });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const points = stops.map((s) => s.coords);

  stops.forEach((s, i) => {
    const icon = L.divIcon({
      className: "",
      html: `<div class="pin pin--${s.kind}">${i + 1}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
    L.marker(s.coords, { icon, title: s.title, zIndexOffset: s.kind === "main" ? 1000 : 0 })
      .addTo(map)
      .bindPopup(`<b>${i + 1}. ${s.title}</b><br>${s.place}<br><a href="#stop-${s.id}">Читать →</a>`);
  });

  map.fitBounds(points, { padding: [30, 30] });

  // Линия маршрута по реальным дорогам (OSRM). Если сервис не ответил —
  // рисуем пунктир «по прямой», чтобы карта всё равно была понятной.
  const info = document.getElementById("route-info");
  const coordStr = points.map(([lat, lon]) => `${lon},${lat}`).join(";");

  fetch(`https://router.project-osrm.org/route/v1/driving/${coordStr}?overview=full&geometries=geojson`)
    .then((r) => r.json())
    .then((data) => {
      if (data.code !== "Ok") throw new Error(data.code);
      const route = data.routes[0];
      L.geoJSON(route.geometry, { style: { color: "#0b6e4f", weight: 5, opacity: 0.85 } }).addTo(map);
      const km = Math.round(route.distance / 1000);
      const h = Math.round(route.duration / 360) / 10;
      info.textContent = `· весь маршрут ≈ ${km} км, ≈ ${h} ч за рулём без остановок`;
    })
    .catch(() => {
      L.polyline(points, { color: "#0b6e4f", weight: 3, dashArray: "6 8" }).addTo(map);
      info.textContent = "· пунктир — схема, не точная дорога";
    });
})();
