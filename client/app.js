const videoEl = document.getElementById("video");
const hud = document.getElementById("hud");

const DASH_URL = "/dash/stream.mpd";
const WT_URL = "https://localhost:4433/wt";

async function fetchAbrProfile() {
  try {
    const response = await fetch("/abr-profile");
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

function initDash() {
  const player = dashjs.MediaPlayer().create();
  player.updateSettings({
    streaming: {
      lowLatencyEnabled: true,
      delay: { liveDelay: 0.5, liveDelayFragmentCount: 1 },
      abr: { autoSwitchBitrate: { video: false } },
      buffer: {
        stableBufferTime: 0.6,
        fastSwitchEnabled: true,
        bufferTimeAtTopQuality: 0.8,
        bufferTimeAtTopQualityLongForm: 0.8,
      },
    },
  });
  player.initialize(videoEl, DASH_URL, true);
  return player;
}

function profileToQualityIndex(profile, maxIndex) {
  const normalized = String(profile || "p0").toLowerCase();
  if (normalized === "p3") return Math.min(3, maxIndex);
  if (normalized === "p2") return Math.min(2, maxIndex);
  if (normalized === "p1") return Math.min(1, maxIndex);
  return 0;
}

async function initWebTransport() {
  const transport = new WebTransport(WT_URL);
  await transport.ready;
  const writer = transport.datagrams.writable.getWriter();

  function sendPose(pose) {
    const buffer = new ArrayBuffer(28);
    const view = new Float32Array(buffer);
    view[0] = performance.now();
    view[1] = pose.x;
    view[2] = pose.y;
    view[3] = pose.z;
    view[4] = pose.pitch;
    view[5] = pose.yaw;
    view[6] = pose.roll;
    writer.write(buffer);
  }

  return { transport, sendPose };
}

async function loadMovementTrace() {
  const response = await fetch("/movement_traces/Linear.json");
  if (!response.ok) {
    throw new Error(`failed to fetch movement trace: ${response.status}`);
  }
  return response.json();
}

async function run() {
  const player = initDash();
  const wt = await initWebTransport();
  const trace = await loadMovementTrace();

  hud.textContent = `TIGAS running: ${trace.length} poses`;

  const abrTimer = setInterval(async () => {
    const abr = await fetchAbrProfile();
    if (!abr) return;
    try {
      const bitrateInfo = player.getBitrateInfoListFor("video") || [];
      if (bitrateInfo.length > 0) {
        const targetQuality = profileToQualityIndex(abr.profile, bitrateInfo.length - 1);
        const currentQuality = player.getQualityFor("video");
        if (currentQuality !== targetQuality) {
          player.setQualityFor("video", targetQuality, true);
        }
      }
    } catch (err) {
      console.warn("ABR profile apply failed", err);
    }
    hud.textContent = `TIGAS poses=${trace.length} abr=${abr.profile} bw=${Math.round(abr.estimated_kbps || 0)}kbps`;
  }, 1000);

  let idx = 0;
  const tick = () => {
    if (idx >= trace.length) {
      hud.textContent = "TIGAS trace complete";
      clearInterval(abrTimer);
      return;
    }

    const sample = trace[idx];
    wt.sendPose({
      x: sample.x ?? 0,
      y: sample.y ?? 0,
      z: sample.z ?? 0,
      pitch: sample.elevation ?? 0,
      yaw: sample.angle ?? 0,
      roll: 0,
    });

    idx += 1;
    const delay = Math.max(10, Number(sample.durationMs ?? 16));
    setTimeout(tick, delay);
  };
  tick();
}

run().catch((err) => {
  console.error(err);
  hud.textContent = `ERROR: ${String(err)}`;
});
