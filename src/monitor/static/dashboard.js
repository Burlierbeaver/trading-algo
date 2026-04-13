// Live dashboard client. Subscribes to /sse and patches the DOM in place.
(() => {
  const $ = (id) => document.getElementById(id);

  const elements = {
    banner: $("engine-banner"),
    state: $("engine-state"),
    hbAge: $("heartbeat-age"),
    serverTime: $("server-time"),
    btnHalt: $("btn-halt"),
    btnResume: $("btn-resume"),
    pnl: {
      equity: $("pnl-equity"),
      cash: $("pnl-cash"),
      daily: $("pnl-daily"),
      unreal: $("pnl-unreal"),
      real: $("pnl-real"),
    },
    positionsBody: $("positions-body"),
    tradesBody: $("trades-body"),
    alerts: $("alerts-list"),
  };

  function fmt(v) { return v === null || v === undefined ? "—" : v; }

  function renderBanner(engine) {
    elements.banner.classList.remove("running", "halted", "stale");
    if (engine.halted) {
      elements.banner.classList.add("halted");
      elements.state.textContent = "HALTED";
    } else if (engine.stale) {
      elements.banner.classList.add("stale");
      elements.state.textContent = "STALE";
    } else {
      elements.banner.classList.add("running");
      elements.state.textContent = "RUNNING";
    }
    elements.hbAge.textContent = engine.heartbeat_age_seconds == null
      ? "n/a"
      : engine.heartbeat_age_seconds.toFixed(1) + "s ago";
    elements.btnHalt.disabled = engine.halted;
    elements.btnResume.disabled = !engine.halted;
  }

  function renderPnL(p) {
    if (!p) {
      Object.values(elements.pnl).forEach((el) => (el.textContent = "—"));
      return;
    }
    elements.pnl.equity.textContent = fmt(p.equity);
    elements.pnl.cash.textContent = fmt(p.cash);
    elements.pnl.daily.textContent = fmt(p.daily_pnl);
    elements.pnl.daily.classList.toggle("neg", Number(p.daily_pnl) < 0);
    elements.pnl.daily.classList.toggle("pos", Number(p.daily_pnl) >= 0);
    elements.pnl.unreal.textContent = fmt(p.unrealized_pnl);
    elements.pnl.real.textContent = fmt(p.realized_pnl);
  }

  function renderPositions(rows) {
    if (!rows || rows.length === 0) {
      elements.positionsBody.innerHTML =
        '<tr><td colspan="5" class="muted">No open positions</td></tr>';
      return;
    }
    elements.positionsBody.innerHTML = rows.map((p) => {
      const neg = Number(p.unrealized_pnl) < 0 ? "neg" : "pos";
      return `<tr>
        <td>${p.symbol}</td>
        <td>${p.quantity}</td>
        <td>${p.avg_price}</td>
        <td>${fmt(p.market_value)}</td>
        <td class="${neg}">${fmt(p.unrealized_pnl)}</td>
      </tr>`;
    }).join("");
  }

  function renderTrades(rows) {
    if (!rows || rows.length === 0) {
      elements.tradesBody.innerHTML =
        '<tr><td colspan="6" class="muted">No recent trades</td></tr>';
      return;
    }
    elements.tradesBody.innerHTML = rows.map((t) => {
      const d = new Date(t.executed_at);
      const hh = d.toLocaleTimeString([], { hour12: false });
      return `<tr>
        <td>${hh}</td>
        <td>${t.symbol}</td>
        <td class="${t.side}">${t.side}</td>
        <td>${t.quantity}</td>
        <td>${t.price}</td>
        <td>${fmt(t.pnl)}</td>
      </tr>`;
    }).join("");
  }

  function renderAlerts(rows) {
    if (!rows || rows.length === 0) {
      elements.alerts.innerHTML = '<li class="muted">No recent alerts</li>';
      return;
    }
    elements.alerts.innerHTML = rows.map((a) => {
      const d = a.created_at ? new Date(a.created_at) : null;
      const hh = d ? d.toLocaleTimeString([], { hour12: false }) : "";
      return `<li class="alert alert-${a.severity}">
        <span class="alert-time">${hh}</span>
        <span class="alert-severity">${a.severity.toUpperCase()}</span>
        <span class="alert-title">${a.title}</span>
        <span class="alert-source">${a.source}</span>
        ${a.detail ? `<span class="alert-detail">${a.detail}</span>` : ""}
      </li>`;
    }).join("");
  }

  function handleSnapshot(snap) {
    renderBanner(snap.engine);
    renderPnL(snap.live_pnl);
    renderPositions(snap.positions);
    renderTrades(snap.recent_trades);
    renderAlerts(snap.recent_alerts);
    elements.serverTime.textContent = new Date(snap.server_time).toLocaleTimeString([], { hour12: false });
  }

  let latestAlerts = [];
  function pushAlert(alert) {
    latestAlerts = [alert, ...latestAlerts].slice(0, 15);
    renderAlerts(latestAlerts);
  }

  function connect() {
    const es = new EventSource("/sse");
    es.addEventListener("snapshot", (e) => {
      try {
        const snap = JSON.parse(e.data);
        latestAlerts = snap.recent_alerts;
        handleSnapshot(snap);
      } catch (err) { console.error("bad snapshot", err); }
    });
    es.addEventListener("alert", (e) => {
      try { pushAlert(JSON.parse(e.data)); } catch (err) { console.error("bad alert", err); }
    });
    es.onerror = () => {
      es.close();
      setTimeout(connect, 2000);
    };
  }

  async function postJSON(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!resp.ok) throw new Error(`${url} failed: ${resp.status}`);
    return resp.json();
  }

  elements.btnHalt.addEventListener("click", async () => {
    if (!confirm("HALT the strategy engine? New orders will stop. Existing positions untouched.")) return;
    elements.btnHalt.disabled = true;
    try { await postJSON("/api/kill", { note: "dashboard operator" }); }
    catch (e) { alert(e.message); elements.btnHalt.disabled = false; }
  });

  elements.btnResume.addEventListener("click", async () => {
    if (!confirm("RESUME the strategy engine?")) return;
    elements.btnResume.disabled = true;
    try { await postJSON("/api/resume", { note: "dashboard operator" }); }
    catch (e) { alert(e.message); elements.btnResume.disabled = false; }
  });

  connect();
})();
