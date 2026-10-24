(() => {
  const $ = (id) => document.getElementById(id);
  const video = $("video");
  const canvas = $("canvas");
  const ctx = canvas.getContext("2d", { alpha: false });
  const live = $("live");
  const RES = [360, 480, 720, 1080];

  const cfg = { fps: 30, res: 720, quality: 0.75, mirror: false, rotate: 0 };
  let facing = "environment";
  let stream = null;
  let track = null;
  let ws = null;
  let open = false;
  let kicked = false;
  let seq = 0;
  let inflight = 0;
  let sentAt = new Map();
  let rtt = 0;
  let sentFps = 0;
  let frames = 0;
  let fpsT0 = performance.now();
  let lastSend = 0;
  let encoding = false;
  let retry = 0;
  let lock = null;
  let torchOn = false;
  let taps = 0;
  const orient = [0, 0, 0];
  const accel = [0, 0, 0];
  const pointers = new Map();
  const downs = new Map();

  function note(text) {
    $("note").textContent = text;
  }

  function phoneName() {
    const ua = navigator.userAgent;
    if (/iPhone/.test(ua)) return "iPhone";
    if (/iPad/.test(ua)) return "iPad";
    const m = ua.match(/Android[^;]*;\s*([^;)]+?)(?:\sBuild|\))/);
    if (m) return m[1].trim();
    if (/Android/.test(ua)) return "Android";
    return "phone";
  }

  function setState(kind, text) {
    const pill = $("state");
    pill.className = "pill " + kind;
    $("stateText").textContent = text;
  }

  async function askSensors() {
    try {
      if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission) {
        await DeviceOrientationEvent.requestPermission();
      }
      if (typeof DeviceMotionEvent !== "undefined" && DeviceMotionEvent.requestPermission) {
        await DeviceMotionEvent.requestPermission();
      }
    } catch (e) {}
    addEventListener("deviceorientation", (e) => {
      orient[0] = e.alpha || 0;
      orient[1] = e.beta || 0;
      orient[2] = e.gamma || 0;
    });
    addEventListener("devicemotion", (e) => {
      const a = e.acceleration;
      if (a && a.x !== null) {
        accel[0] = a.x || 0;
        accel[1] = a.y || 0;
        accel[2] = a.z || 0;
      }
    });
  }

  async function camera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    const long = Math.round(cfg.res * 16 / 9);
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: facing },
        width: { ideal: long },
        height: { ideal: cfg.res },
        frameRate: { ideal: cfg.fps },
      },
    });
    track = stream.getVideoTracks()[0];
    video.srcObject = stream;
    await video.play().catch(() => {});
    const settings = track.getSettings ? track.getSettings() : {};
    const front = settings.facingMode ? settings.facingMode === "user" : facing === "user";
    live.classList.toggle("front", front);
    const caps = track.getCapabilities ? track.getCapabilities() : {};
    $("torch").hidden = !caps.torch;
    torchOn = false;
    $("torch").classList.remove("on");
    $("res").textContent = cfg.res + "p";
  }

  function connect() {
    if (ws) {
      ws.onclose = null;
      ws.close();
    }
    setState("", retry ? "reconnecting" : "connecting");
    ws = new WebSocket(`wss://${location.host}/ws`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      open = true;
      retry = 0;
      inflight = 0;
      sentAt.clear();
      ws.send(JSON.stringify({ t: "hello", name: phoneName() }));
      setState("ok", "live");
    };
    ws.onmessage = async (e) => {
      if (typeof e.data !== "string") return;
      let m;
      try { m = JSON.parse(e.data); } catch (err) { return; }
      if (m.t === "ack") {
        inflight = Math.max(0, inflight - 1);
        const t = sentAt.get(m.n);
        if (t) {
          const ms = performance.now() - t;
          rtt = rtt ? rtt * 0.85 + ms * 0.15 : ms;
          sentAt.delete(m.n);
        }
      } else if (m.t === "hi") {
        const changed = m.res && m.res !== cfg.res;
        Object.assign(cfg, {
          fps: m.fps || cfg.fps,
          res: m.res || cfg.res,
          quality: m.quality || cfg.quality,
          mirror: !!m.mirror,
          rotate: m.rotate || 0,
        });
        if (changed) await camera().catch(() => {});
      } else if (m.t === "kick") {
        kicked = true;
        $("kicked").hidden = false;
      }
    };
    ws.onclose = () => {
      open = false;
      if (kicked) {
        setState("bad", "paused");
        return;
      }
      setState("bad", "lost the pc");
      retry++;
      setTimeout(connect, Math.min(4000, 400 * retry));
    };
  }

  function size() {
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return null;
    const long = Math.round(cfg.res * 16 / 9);
    const s = Math.min(1, long / Math.max(vw, vh), cfg.res / Math.min(vw, vh));
    let w = Math.round(vw * s / 2) * 2;
    let h = Math.round(vh * s / 2) * 2;
    if (cfg.rotate === 90 || cfg.rotate === 270) [w, h] = [h, w];
    return [w, h, vw, vh];
  }

  function draw(w, h) {
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.translate(w / 2, h / 2);
    ctx.rotate(cfg.rotate * Math.PI / 180);
    if (cfg.mirror) ctx.scale(-1, 1);
    const sw = cfg.rotate === 90 || cfg.rotate === 270 ? h : w;
    const sh = cfg.rotate === 90 || cfg.rotate === 270 ? w : h;
    ctx.drawImage(video, -sw / 2, -sh / 2, sw, sh);
  }

  function blob() {
    return new Promise((res) => canvas.toBlob(res, "image/jpeg", cfg.quality));
  }

  async function send() {
    const dims = size();
    if (!dims) return;
    const [w, h] = dims;
    encoding = true;
    try {
      draw(w, h);
      const b = await blob();
      if (!b || !open) return;
      const body = await b.arrayBuffer();
      const packet = new Uint8Array(8 + body.byteLength);
      const view = new DataView(packet.buffer);
      seq = (seq + 1) >>> 0;
      view.setUint32(0, seq);
      view.setUint16(4, w);
      view.setUint16(6, h);
      packet.set(new Uint8Array(body), 8);
      ws.send(packet);
      inflight++;
      sentAt.set(seq, performance.now());
      if (sentAt.size > 30) sentAt.delete(sentAt.keys().next().value);
      frames++;
    } finally {
      encoding = false;
    }
  }

  function loop(now) {
    requestAnimationFrame(loop);
    if (now - fpsT0 >= 1000) {
      sentFps = frames * 1000 / (now - fpsT0);
      frames = 0;
      fpsT0 = now;
      $("stats").textContent = open ? `${Math.round(sentFps)} fps · ${Math.round(rtt)} ms` : "";
    }
    if (!open || encoding || kicked || video.readyState < 2) return;
    if (inflight >= 2) {
      const oldest = sentAt.size ? sentAt.values().next().value : 0;
      if (oldest && now - oldest > 1500) {
        inflight = 0;
        sentAt.clear();
      }
      return;
    }
    if (now - lastSend < 1000 / cfg.fps - 2) return;
    lastSend = now;
    send();
  }

  function sensorTick() {
    if (!open || ws.readyState !== 1) return;
    const r = $("surface").getBoundingClientRect();
    const pts = [];
    for (const p of pointers.values()) {
      pts.push([+(((p.x - r.left) / r.width)).toFixed(4), +(((p.y - r.top) / r.height)).toFixed(4)]);
    }
    ws.send(JSON.stringify({
      t: "s",
      o: orient.map((v) => +v.toFixed(2)),
      a: accel.map((v) => +v.toFixed(3)),
      p: pts,
      k: taps,
    }));
  }

  function statTick() {
    if (open) ws.send(JSON.stringify({ t: "stat", rtt: Math.round(rtt), front: live.classList.contains("front") }));
  }

  function drawDots() {
    const box = $("dots");
    box.textContent = "";
    for (const p of pointers.values()) {
      const d = document.createElement("i");
      d.style.left = p.x + "px";
      d.style.top = p.y + "px";
      box.appendChild(d);
    }
  }

  function touches() {
    const s = $("surface");
    s.addEventListener("pointerdown", (e) => {
      s.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      downs.set(e.pointerId, { x: e.clientX, y: e.clientY, t: performance.now() });
      drawDots();
    });
    s.addEventListener("pointermove", (e) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      drawDots();
    });
    const up = (e) => {
      const d = downs.get(e.pointerId);
      if (d && performance.now() - d.t < 250 && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 18) taps++;
      pointers.delete(e.pointerId);
      downs.delete(e.pointerId);
      drawDots();
    };
    s.addEventListener("pointerup", up);
    s.addEventListener("pointercancel", up);
  }

  async function wake() {
    try {
      if ("wakeLock" in navigator) lock = await navigator.wakeLock.request("screen");
    } catch (e) {}
  }

  async function start() {
    if (!window.isSecureContext || !navigator.mediaDevices) {
      note("this needs the https link handoff printed on your pc");
      return;
    }
    $("start").disabled = true;
    await askSensors();
    try {
      await camera();
    } catch (e) {
      $("start").disabled = false;
      note(e && e.name === "NotAllowedError" ? "camera blocked. allow it in your browser settings and try again" : "couldn't open the camera");
      return;
    }
    $("intro").hidden = true;
    live.hidden = false;
    touches();
    connect();
    wake();
    requestAnimationFrame(loop);
    setInterval(sensorTick, 16);
    setInterval(statTick, 1000);
  }

  $("start").addEventListener("click", start);

  $("flip").addEventListener("click", async () => {
    facing = facing === "environment" ? "user" : "environment";
    try { await camera(); } catch (e) {}
  });

  $("res").addEventListener("click", async () => {
    cfg.res = RES[(RES.indexOf(cfg.res) + 1) % RES.length];
    try { await camera(); } catch (e) {}
  });

  $("torch").addEventListener("click", async () => {
    if (!track) return;
    torchOn = !torchOn;
    try {
      await track.applyConstraints({ advanced: [{ torch: torchOn }] });
    } catch (e) {
      torchOn = false;
    }
    $("torch").classList.toggle("on", torchOn);
  });

  $("dim").addEventListener("click", () => {
    $("shade").hidden = false;
  });

  $("shade").addEventListener("click", () => {
    $("shade").hidden = true;
  });

  $("retake").addEventListener("click", () => {
    kicked = false;
    $("kicked").hidden = true;
    retry = 0;
    connect();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      wake();
      if (!open && !kicked && ws && ws.readyState > 1) connect();
    }
  });

  if (!window.isSecureContext) note("this needs the https link handoff printed on your pc");
})();
