console.log("🟣 Velvet build:", "API_ONLY_SCREEN_V1+RITUAL_COMPLETE_HTTP", new Date().toISOString());
console.log("✅ app.js chargé — VelvetOracle");

// =========================================================================
// Velvet Typo Canon — Normalisation (Morena)
// =========================================================================
function velvetNormalize(input) {
  if (typeof input !== "string") return input;

  // 1) Canonise ligatures first (they don't decompose cleanly in NFD)
  let s = input
    .replace(/œ/g, "oe")
    .replace(/Œ/g, "OE")
    .replace(/æ/g, "ae")
    .replace(/Æ/g, "AE");

  // 2) Strip diacritics / special combining marks (Morena coverage is limited)
  //    Examples fixed: ø → o, ǫ → o, ñ → n, é → e, etc.
  s = s.normalize("NFD").replace(/[̀-ͯ]/g, "");

  // 3) Small curated substitutions (kept for readability)
  s = s
    .replace(/ō/g, "o")
    .replace(/Ō/g, "O");

  return s;
}

// =========================================================================
// Velvet Font Choice — Velvet / Standard (persistant)
// =========================================================================
const FONT_STORAGE_KEY = "vo_font_mode"; // "velvet" | "standard"

function applyFontMode(mode) {
  const m = (mode === "standard") ? "standard" : "velvet";

  const root = document.documentElement;

  if (m === "standard") {
    root.style.setProperty(
      "--font-display",
      `-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,-webkit-system-font,"Segoe UI",Roboto,sans-serif`
    );
    root.style.setProperty(
      "--font-body",
      `-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,-webkit-system-font,"Segoe UI",Roboto,sans-serif`
    );
  } else {
    root.style.setProperty(
      "--font-display",
      `"Morena",-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,-webkit-system-font,"Segoe UI",Roboto,sans-serif`
    );
    root.style.setProperty(
      "--font-body",
      `-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,-webkit-system-font,"Segoe UI",Roboto,sans-serif`
    );
  }

  try { localStorage.setItem(FONT_STORAGE_KEY, m); } catch (_) {}

  const btnVelvet = document.getElementById("vo_font_velvet");
  const btnStandard = document.getElementById("vo_font_standard");
  const onStyle = `border:1px solid rgba(200,169,106,.85); background:rgba(200,169,106,.12); color:rgba(245,242,232,.92);`;
  const offStyle = `border:1px solid rgba(200,169,106,.28); background:rgba(0,0,0,.22); color:rgba(245,242,232,.72);`;

  if (btnVelvet && btnStandard) {
    btnVelvet.style.cssText = btnVelvet.style.cssText.replace(onStyle, "").replace(offStyle, "") + (m === "velvet" ? onStyle : offStyle);
    btnStandard.style.cssText = btnStandard.style.cssText.replace(onStyle, "").replace(offStyle, "") + (m === "standard" ? onStyle : offStyle);
  }
}

function getSavedFontMode() {
  try {
    const v = localStorage.getItem(FONT_STORAGE_KEY);
    return (v === "standard" || v === "velvet") ? v : "velvet";
  } catch (_) {
    return "velvet";
  }
}

function injectFontChooser() {
  const chamber = document.querySelector(".screen-chamber .chamber");
  if (!chamber) return;

  document.querySelectorAll("#vo_font_choice").forEach(n => n.remove());

  const legacyTitles = Array.from(chamber.querySelectorAll("*"))
    .filter(el => (el.textContent || "").trim() === "Typographie");

  for (const t of legacyTitles) {
    const block =
      t.closest(".typo-choice") ||
      t.closest("[data-typo]") ||
      t.closest(".chamber-typo") ||
      t.parentElement;

    if (block && block !== chamber) block.remove();
  }

  if (document.getElementById("vo_font_choice")) return;

  const startBtn = document.getElementById("btn-start-ritual");
  if (!startBtn) return;

  const wrap = document.createElement("div");
  wrap.id = "vo_font_choice";
  wrap.style.cssText = `
    margin: 10px 0 14px 0;
    display:flex;
    flex-direction:column;
    gap:10px;
  `;

  const label = document.createElement("div");
  label.textContent = "Police d’affichage";
  label.style.cssText = `
    font-size:11px;
    letter-spacing:.22em;
    text-transform:uppercase;
    color:rgba(245,242,232,.58);
    font-weight:700;
  `;

  const row = document.createElement("div");
  row.style.cssText = `display:flex; gap:10px;`;

  const baseBtnStyle = `
    flex:1;
    border-radius:999px;
    padding:11px 10px;
    cursor:pointer;
    font-weight:800;
    letter-spacing:.14em;
    text-transform:uppercase;
    font-size:11px;
    font-family: var(--font-display);
    transition: transform .12s ease-out, filter .12s ease-out;
    border:1px solid rgba(200,169,106,.28);
    background:rgba(0,0,0,.22);
    color:rgba(245,242,232,.72);
  `;

  const btnVelvet = document.createElement("button");
  btnVelvet.type = "button";
  btnVelvet.id = "vo_font_velvet";
  btnVelvet.textContent = "Police Velvet";
  btnVelvet.style.cssText = baseBtnStyle;

  const btnStandard = document.createElement("button");
  btnStandard.type = "button";
  btnStandard.id = "vo_font_standard";
  btnStandard.textContent = "Police standard";
  btnStandard.style.cssText = baseBtnStyle;

  btnVelvet.addEventListener("click", () => applyFontMode("velvet"));
  btnStandard.addEventListener("click", () => applyFontMode("standard"));

  row.appendChild(btnVelvet);
  row.appendChild(btnStandard);

  wrap.appendChild(label);
  wrap.appendChild(row);

  startBtn.parentNode.insertBefore(wrap, startBtn);

  applyFontMode(getSavedFontMode());
}

// =========================================================================
// ✅ Fullscreen — Variant A “Le Sceau” (Velvet)
// =========================================================================
function requestVelvetFullscreen(){
  const tg = window.Telegram?.WebApp;
  try { tg?.requestFullscreen?.(); } catch(e) {}
  try { tg?.expand?.(); } catch(e) {}
  setTimeout(() => { try{ tg?.expand?.(); }catch(e){} }, 250);
  setTimeout(() => { try{ tg?.expand?.(); }catch(e){} }, 900);
}

function injectFullscreenSeal(){
  const chamber = document.querySelector(".screen-chamber .chamber");
  if (!chamber) return;

  if (document.getElementById("vo_fs_seal_wrap")) return;

  const wrap = document.createElement("div");
  wrap.id = "vo_fs_seal_wrap";
  wrap.className = "fs-seal-wrap";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "vo_fs_seal_btn";
  btn.className = "fs-seal";
  btn.setAttribute("aria-label", "Activer le plein écran");

  btn.innerHTML = `
    <svg class="fs-seal-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <span class="fs-seal-label">Plein écran</span>
  `;

  btn.addEventListener("click", () => {
    try { primeTickAudio(); } catch(e) {}
    requestVelvetFullscreen();
    btn.classList.add("active");
    setTimeout(() => btn.classList.add("settled"), 700);
  });

  wrap.appendChild(btn);

  const typoWrap = document.getElementById("vo_font_choice");
  if (typoWrap && typoWrap.parentNode === chamber){
    chamber.insertBefore(wrap, typoWrap);
  } else {
    chamber.insertBefore(wrap, chamber.firstChild);
  }

  const tg = window.Telegram?.WebApp;
  if (tg?.isExpanded) btn.classList.add("settled");
}

// =========================================================================
// ✅ Velvet Oracle — Questions dynamiques (API)
// =========================================================================

// === Sécurité : capture globale des erreurs ===
window.addEventListener("error", (e) => {
  console.error("💥 JS error:", e?.message, e?.filename, e?.lineno);
});
window.addEventListener("unhandledrejection", (e) => {
  console.error("💥 Promise rejection:", e?.reason);
});

console.log("✅ DOM ready — init()");

document.addEventListener("DOMContentLoaded", () => {
  try { injectFullscreenSeal(); } catch(e) {}
});

function getQueryParam(name) {
  try {
    const u = new URL(window.location.href);
    return u.searchParams.get(name) || "";
  } catch (e) {
    return "";
  }
}

const DEFAULT_API_URL = "https://oracle--velvet-elite.replit.app";
let QUESTIONS_API_URL = (getQueryParam("api") || DEFAULT_API_URL).replace(/\/+$/, "");

// ✅ Hard override: old/dead backend links (Telegram cache) still pass api=velvet-mcp-core.
// We neutralize it here so even ancient buttons keep working.
if (QUESTIONS_API_URL.includes("velvet-mcp-core")) {
  console.warn("🟠 OVERRIDE api (old backend) →", QUESTIONS_API_URL, "→", DEFAULT_API_URL);
  QUESTIONS_API_URL = DEFAULT_API_URL;
}
console.log("✅ API BASE =", QUESTIONS_API_URL);

const QUESTIONS_COUNT = 15;

// === Runtime data ===
let QUIZ_DATA = [];
let TOTAL_QUESTIONS = QUESTIONS_COUNT;

const LETTERS = ["A","B","C","D"];

const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
if (tg && typeof tg.ready === "function") tg.ready();

// ✅ Auto-expand gate: only keep forcing expand during the ritual screens
let VO_AUTO_EXPAND_ENABLED = true;


// ✅ TELEGRAM viewport guard
try {
  const __tg = window.Telegram?.WebApp;
  if (__tg?.onEvent) {
    __tg.onEvent("viewportChanged", () => {
      if (VO_AUTO_EXPAND_ENABLED && !__tg.isExpanded) __tg.expand?.();
    });
  } else if (__tg?.onViewportChanged) {
    __tg.onViewportChanged(() => {
      if (VO_AUTO_EXPAND_ENABLED && !__tg.isExpanded) __tg.expand?.();
    });
  }
} catch (e) {}

applyFontMode(getSavedFontMode());

// =========================================================================
// ✅ RITUEL: identité session / attempt_id (HTTP visible)
// =========================================================================
let ritualAttemptId = null;
let ritualPlayerTelegramUserId = null;

/** safe: récupère l'user id Telegram si dispo */
function getTelegramUserId(){
  try {
    const id = tg?.initDataUnsafe?.user?.id;
    if (id !== undefined && id !== null && String(id).length > 0) return String(id);
  } catch(e){}
  return "";
}

/** attempt_id local fallback (si /ritual/start absent) */
function generateLocalAttemptId(){
  const rand = Math.random().toString(16).slice(2, 8);
  return `AT-LOCAL-${Date.now()}-${rand}`;
}

/** headers canon pour backend (initData si dispo) */
function buildApiHeaders(){
  const headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
  };
  const initData = tg?.initData || "";
  if (initData) headers["X-Telegram-InitData"] = initData;
  return headers;
}


// =========================================================================
// ✅ UX latence — Overlay de préparation (rituel)
// =========================================================================
function showRitualLoading(){
  const el = document.getElementById("ritual-loading");
  if (el){
    el.classList.remove("hidden");
    el.classList.remove("settling"); // ✅ important : laisse l’animation tourner
  }
}

function hideRitualLoading(){
  const el = document.getElementById("ritual-loading");
  if (el){
    el.classList.remove("settling");
    el.classList.add("hidden");
  }
}


/** tente de créer un attempt côté backend (visible dans Network) */
async function ensureAttemptStarted(){
  if (ritualAttemptId) return ritualAttemptId;

  ritualPlayerTelegramUserId = ritualPlayerTelegramUserId || getTelegramUserId();

  const url = `${QUESTIONS_API_URL}/ritual/start`;
  const body = {
    mode: "rituel_full_v1",
    telegram_user_id: ritualPlayerTelegramUserId || undefined
  };

  try {
    console.log("🟡 HTTP /ritual/start →", url);
    const r = await fetch(url, { method: "POST", headers: buildApiHeaders(), body: JSON.stringify(body), cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const attempt = data?.attempt_id || data?.attemptId || data?.id || "";
    if (!attempt) throw new Error("NO_ATTEMPT_ID");
    ritualAttemptId = String(attempt);
    console.log("✅ attempt_id obtenu =", ritualAttemptId);
    return ritualAttemptId;
  } catch (e) {
    // fallback propre: on ne bloque pas le rituel
    ritualAttemptId = generateLocalAttemptId();
    console.warn("⚠️ /ritual/start indisponible → fallback attempt_id =", ritualAttemptId, "| reason:", e?.message || e);
    return ritualAttemptId;
  }
}

/** envoie la clôture au backend (visible dans Network) */
async function postRitualComplete(payload){
  // payload est ton objet final (score/temps/answers/feedback etc.)
  const attempt_id = ritualAttemptId || generateLocalAttemptId();
  ritualAttemptId = attempt_id;

  ritualPlayerTelegramUserId = ritualPlayerTelegramUserId || getTelegramUserId();

  const url = `${QUESTIONS_API_URL}/ritual/complete`;

  // ✅ body minimal + ton payload en parallèle
  const body = {
    attempt_id,
    telegram_user_id: ritualPlayerTelegramUserId || undefined,
    mode: payload?.mode || "rituel_full_v1",
    score_raw: Number.isFinite(Number(payload?.score)) ? Number(payload.score) : undefined,
    score_max: Number.isFinite(Number(payload?.total)) ? Number(payload.total) : undefined,
    time_total_seconds: Number.isFinite(Number(payload?.time_total_seconds ?? payload?.time_spent_seconds)) ? Number(payload.time_total_seconds ?? payload.time_spent_seconds) : undefined,
    completed_at: new Date().toISOString(),
    // bonus (non bloquant si backend ignore)
    client_payload: payload,
    // ✅ direct fields for backend (no guessing)
    answers: payload?.answers || undefined,
    feedback_text: payload?.comment_text || payload?.feedback_text || ""
  };

  console.log("🟡 HTTP /ritual/complete →", url, "| attempt_id =", attempt_id);

  const r = await fetch(url, {
    method: "POST",
    headers: buildApiHeaders(),
    body: JSON.stringify(body),
    cache: "no-store",
    keepalive: true
  });

  let respText = "";
  try { respText = await r.text(); } catch(e){}

  if (!r.ok) {
    console.error("❌ /ritual/complete FAILED", r.status, respText);
    throw new Error(`RITUAL_COMPLETE_HTTP_${r.status}`);
  }

  console.log("✅ /ritual/complete OK", r.status, respText);
  return { ok: true, status: r.status, body: respText };
}

// ====== API LOAD ======
function normalizeQuestion(q, idx){
  const id = q.id ?? q.ID ?? q.ID_question ?? (idx + 1);

  const domain =
    q.domain ?? q.Domaine ?? q.domaine ?? q.DOMAINE ?? "—";

  const levelRaw =
    q.level ?? q.Niveau ?? q.niveau ?? q.LEVEL ?? 0;
  const level = Number.isFinite(Number(levelRaw)) ? Number(levelRaw) : levelRaw;

  const question = q.question ?? q.Question ?? q.texte ?? "";

  let options = q.options ?? q.Options ?? q.choices ?? q["Options (JSON)"] ?? [];
  if (typeof options === "string") {
    try { options = JSON.parse(options); } catch(e) { options = []; }
  }

  const correct_index =
    Number.isInteger(q.correct_index) ? q.correct_index :
    Number.isInteger(q.Correct_index) ? q.Correct_index :
    (Number.isFinite(Number(q.correct_index)) ? Number(q.correct_index) :
     Number.isFinite(Number(q.Correct_index)) ? Number(q.Correct_index) : 0);

  const explanation =
    q.explanation ?? q.Explanation ?? q.Explication ?? q.explication ?? q["Explication"] ?? "";

  const opt = Array.isArray(options) ? options.slice(0,4) : [];
  while (opt.length < 4) opt.push("");

  return {
    id,
    domain,
    level,
    question: velvetNormalize(question),
    options: opt.map(x => velvetNormalize(x)),
    correct_index,
    explanation: velvetNormalize(explanation)
  };
}

async function fetchQuestionsFromAPI(){
  if (!QUESTIONS_API_URL) {
    throw new Error("API_MISSING: QUESTIONS_API_URL non défini");
  }

  const url = `${QUESTIONS_API_URL}/questions/random?count=${encodeURIComponent(QUESTIONS_COUNT)}&t=${Date.now()}`;

  const initData = tg?.initData || "";
  const headers = { "Accept": "application/json" };
  if (initData) headers["X-Telegram-InitData"] = initData;

  console.log("API URL utilisée →", url);

  const r = await fetch(url, { method: "GET", headers, cache: "no-store" });
  if (!r.ok) throw new Error(`API HTTP ${r.status}`);

  const data = await r.json();
  const arr = data?.questions || data?.items || data || [];
  if (!Array.isArray(arr) || arr.length < 1) throw new Error("API: aucune question");

  const picked = arr.slice(0, QUESTIONS_COUNT).map(normalizeQuestion);
  if (picked.length < QUESTIONS_COUNT) throw new Error("API: pas assez de questions");

  for (const q of picked){
    if (!q.question || !Array.isArray(q.options) || q.options.length !== 4) {
      throw new Error("API: format question invalide");
    }
  }

  return picked;
}

function renderVelvetUnavailableScreen(){
  const el = document.getElementById("app") || document.body;

  el.innerHTML = `
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:26px;background:#000;">
      <div style="width:min(560px, 92vw); border:1px solid rgba(216,199,160,.22); border-radius:22px; padding:26px 22px; background:rgba(0,0,0,.62); box-shadow:0 0 80px rgba(216,199,160,.10); text-align:center;">
        <div style="font-family:Morena, system-ui; font-size:13px; letter-spacing:.22em; text-transform:uppercase; color:rgba(216,199,160,.75); margin-bottom:10px;">
          Velvet Oracle
        </div>

        <div style="font-family:Morena, system-ui; font-size:24px; color:#d8c7a0; margin:0 0 10px 0;">
          Le rituel est momentanément indisponible
        </div>

        <div style="font-family:Morena, system-ui; font-size:15px; line-height:1.55; color:rgba(216,199,160,.78); margin-bottom:18px;">
          Nous ne pouvons pas ouvrir cette session pour l’instant.<br/>
          Reviens dans quelques instants. Sans bruit. Sans urgence.
        </div>

        <button id="vo_retry"
          style="appearance:none;border:1px solid rgba(216,199,160,.35); background:rgba(216,199,160,.08);
                 color:#d8c7a0; padding:12px 16px; border-radius:999px; cursor:pointer;
                 font-family:Morena, system-ui; letter-spacing:.12em; text-transform:uppercase; font-size:12px;">
          Réessayer
        </button>

        <div style="margin-top:14px; font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:rgba(216,199,160,.45);">
          Service Velvet
        </div>
      </div>
    </div>
  `;

  document.getElementById("vo_retry")?.addEventListener("click", () => location.reload());
}

async function ensureQuizData(){
  try{
    const fromApi = await fetchQuestionsFromAPI();
    if (Array.isArray(fromApi) && fromApi.length === QUESTIONS_COUNT){
      QUIZ_DATA = fromApi;
      TOTAL_QUESTIONS = QUESTIONS_COUNT;
      console.log("✅ QUIZ_DATA chargé depuis l'API :", QUIZ_DATA.length);
      return;
    }
    throw new Error("API: payload inattendu");
  } catch (e) {
    console.error("🚫 Questions API FAILED:", e?.message || e);
    renderVelvetUnavailableScreen();
    throw e;
  }
}

// =========================================================================
// RITUEL (moteur)
// =========================================================================

let currentIndex = 0;
let currentSelection = null;
let currentShuffle = [];
let answers = [];
let pendingAnswer = null;
let showingExplanation = false;

let ritualStartTime = null;
let totalTimer = null;
let lastTotalSeconds = 0;

let questionTimer = null;
let questionRemaining = 45;

let explanationCountdown = null;
let explanationRemaining = 60;

let finalScore = 0;
let finalEnrichedAnswers = [];
let finalTotalSeconds = 0;
let ritualFinished = false;
let finalPayload = null;
let finalPayloadSent = false;
let finalPayloadHttpSent = false;

// ✅ Compteur “bonnes réponses” live
let correctCount = 0;

// ✅ Score live
let hasAnyAnswer = false;
let railTotalSeconds = 45;

// ===== Tick =====
let tickPrimed = false;
function primeTickAudio(){
  if (tickPrimed) return;
  tickPrimed = true;
  const a = document.getElementById("velvet-tick");
  if (!a) return;
  a.volume = 0.01;
  const p = a.play();
  if (p && typeof p.then === "function"){
    p.then(() => { a.pause(); a.currentTime = 0; a.volume = 0.22; })
     .catch(() => { a.volume = 0.22; });
  } else {
    a.pause(); a.currentTime = 0; a.volume = 0.22;
  }
}

function velvetTick(){
  if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === "function"){
    tg.HapticFeedback.impactOccurred("light");
  }
  const a = document.getElementById("velvet-tick");
  if (a){
    a.currentTime = 0;
    a.volume = 0.22;
    a.play().catch(()=>{});
  }
}

function formatSeconds(sec){
  const s = Math.max(0, sec);
  const m = Math.floor(s/60);
  const r = s % 60;
  return `${String(m).padStart(2,"0")}:${String(r).padStart(2,"0")}`;
}
function shuffleArray(arr){
  for (let i = arr.length-1; i>0; i--){
    const j = Math.floor(Math.random()*(i+1));
    [arr[i],arr[j]] = [arr[j],arr[i]];
  }
  return arr;
}

function isSignatureIndex(idx0){ return idx0 === 2 || idx0 === 7 || idx0 === 12; }

function setSignatureUI(active){
  const card = document.querySelector(".quiz-card");
  if (!card) return;
  card.classList.toggle("signature", !!active);

  const stroke = document.querySelector(".clock-ring-stroke");
  if (stroke) stroke.style.display = active ? "block" : "none";
}

function setTimerMode(mode){
  const el = document.getElementById("quiz-timer");
  if (!el) return;
  el.classList.toggle("pulse", mode === "lecture");
}

function setRailMode(mode){
  const rail = document.getElementById("time-rail");
  if (!rail) return;
  rail.classList.toggle("lecture", mode === "lecture");
}

function setRailProgress(remaining, total){
  const fill = document.getElementById("time-fill");
  if (!fill) return;
  const t = Math.max(1, total || 1);
  const r = Math.max(0, Math.min(remaining, t));
  fill.style.transform = `scaleX(${r / t})`;
  // VO — Ring : progression circulaire (p = 1 - fraction restante)
  try{
    const t2 = Math.max(1, total || 1);
    const r2 = Math.max(0, Math.min(remaining, t2));
    const fracRemaining = (r2 / t2);
    voUpdateTimerRing(1 - fracRemaining);
  }catch(e){}

}


// ===========================
// VO — HALO RING TEMPOREL (autour de la question)
// Progression circulaire non-numérique synchronisée avec le timer interne.
// ===========================
function voEnsureTimerRing(){
  const host = document.getElementById("quiz-question");
  if (!host) return null;
  if (!host.style.position) host.style.position = "relative";
  let ring = host.querySelector(".vo-timer-ring");
  if (!ring){
    ring = document.createElement("div");
    ring.className = "vo-timer-ring";
    host.appendChild(ring);
  }
  return ring;
}

function voUpdateTimerRing(p){ // p: 0..1 (0 début, 1 fin)
  const ring = voEnsureTimerRing();
  if (!ring) return;
  const clamped = Math.max(0, Math.min(1, p));
  ring.classList.add("active");
  ring.style.setProperty("--p", String(clamped));
}

function voResetTimerRing(){
  const ring = voEnsureTimerRing();
  if (!ring) return;
  ring.classList.remove("active");
  ring.style.setProperty("--p", "0");
}


function spawnRipple(btn, event){
  if (!btn) return;
  const rect = btn.getBoundingClientRect();
  const x = (event?.clientX ?? (rect.left + rect.width/2)) - rect.left;
  const y = (event?.clientY ?? (rect.top + rect.height/2)) - rect.top;
  const ripple = document.createElement("span");
  ripple.className = "ripple";
  const size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${x - size/2}px`;
  ripple.style.top  = `${y - size/2}px`;
  btn.appendChild(ripple);
  ripple.addEventListener("animationend", () => ripple.remove());
}

function performVerdictReveal(correctDisplayIndex, applyStates){
  const wrap = document.getElementById("quiz-options");
  if (wrap) wrap.classList.add("veil");

  const correctBtn = optionButtons[correctDisplayIndex];
  if (correctBtn){
    const sweep = document.createElement("span");
    sweep.className = "light-sweep";
    correctBtn.appendChild(sweep);
    sweep.addEventListener("animationend", () => sweep.remove());
  }

  if (isSignatureIndex(currentIndex)) velvetTick();

  setTimeout(() => {
    if (wrap) wrap.classList.remove("veil");
    applyStates();
  }, 750);
}

const screenIntro = document.querySelector(".screen-intro");
const screenChamber = document.querySelector(".screen-chamber");
const screenQuiz = document.querySelector(".screen-quiz");
const screenResult = document.querySelector(".screen-result");
const screenFeedbackFinal = document.querySelector(".screen-feedback-final");

const btnReadyEl = document.getElementById("btn-ready");
const btnStartRitualEl = document.getElementById("btn-start-ritual");

const quizIndexEl = document.getElementById("quiz-index");
const quizTotalEl = document.getElementById("quiz-total");
const quizQuestionEl = document.getElementById("quiz-question");
const quizMetaEl = document.getElementById("quiz-meta");
const quizTimerEl = document.getElementById("quiz-timer");
const quizExplanationEl = document.getElementById("quiz-explanation");
const optionButtons = document.querySelectorAll(".quiz-option");
const btnNext = document.getElementById("btn-next");
const quizCorrectCountEl = document.getElementById("quiz-correct-count");
const quizCurrentIndexEl = document.getElementById("quiz-current-index");

const resultTitleEl = document.getElementById("result-title");
const resultSubtitleEl = document.getElementById("result-subtitle");
const resultScoreEl = document.getElementById("result-score");
const resultTimeEl = document.getElementById("result-time");
const btnGoFeedback = document.getElementById("btn-go-feedback");

const feedbackFinalTextEl = document.getElementById("feedback-final-text");

// ✅ Mobile UX: prevent any fullscreen/expand forcing when keyboard opens on feedback
if (feedbackFinalTextEl){
  feedbackFinalTextEl.addEventListener("focus", () => { try { VO_AUTO_EXPAND_ENABLED = false; } catch(e) {} });
}

const feedbackFinalSendBtn = document.getElementById("btn-feedback-final-send");
const feedbackFinalMessageEl = document.getElementById("feedback-final-message");
const feedbackFinalSignatureEl = document.getElementById("feedback-final-signature");
const feedbackFinalCloseBtn = document.getElementById("btn-feedback-close");

console.assert(btnReadyEl, "❌ btn-ready introuvable");
console.assert(btnStartRitualEl, "❌ btn-start-ritual introuvable");
console.assert(quizQuestionEl, "❌ quiz-question introuvable");
console.assert(document.getElementById("quiz-options"), "❌ quiz-options introuvable");
console.assert(btnNext, "❌ btn-next introuvable");

if (btnReadyEl) {
  btnReadyEl.addEventListener("click", () => {
    console.log("🟡 CLICK btn-ready — passage Intro → Chambre");
    primeTickAudio();
    if (screenIntro) screenIntro.classList.add("hidden");
    if (screenChamber) screenChamber.classList.remove("hidden");

    try { injectFullscreenSeal(); } catch(e) {}
    try { injectFontChooser(); } catch(e) {}
  });
}

if (btnStartRitualEl) {
  btnStartRitualEl.addEventListener("click", async () => {
    window.Telegram?.WebApp?.expand();
    window.Telegram?.WebApp?.requestFullscreen?.();
    setTimeout(() => window.Telegram?.WebApp?.expand(), 250);
    console.log("🟡 CLICK btn-start-ritual — démarrage rituel");
    VO_AUTO_EXPAND_ENABLED = true;
    primeTickAudio();
    if (screenChamber) screenChamber.classList.add("hidden");
    if (screenQuiz) screenQuiz.classList.remove("hidden");

    hasAnyAnswer = false;
    try { setLiveScoreVisibility(false); } catch(e) {}
    try { updateCorrectCounter(); } catch(e) {}

    requestAnimationFrame(() => {
      window.Telegram?.WebApp?.expand?.();
      setTimeout(() => window.Telegram?.WebApp?.expand?.(), 250);
    });

    // ✅ UX latence : couvre /ritual/start + /questions/random
    showRitualLoading();

    try {
      // 1) attempt_id (peut être lent)
      try { await ensureAttemptStarted(); } catch(e) {}

      // 2) questions (latence principale)
      await ensureQuizData();
    } finally {
      hideRitualLoading();
    }

    startRituel();});
}

function setLiveScoreVisibility(show){
  const els = [quizCorrectCountEl, quizCurrentIndexEl].filter(Boolean);

  for (const el of els){
    const row =
      el.closest?.(".quiz-live-score") ||
      el.closest?.(".quiz-correct-line") ||
      el.closest?.(".quiz-correct") ||
      el.parentElement;

    if (!row) continue;

    if (row.dataset && row.dataset.voPrevDisplay === undefined){
      row.dataset.voPrevDisplay = row.style.display || "";
    }
    row.style.display = show ? (row.dataset?.voPrevDisplay ?? "") : "none";
  }
}

function updateCorrectCounter(){
  if (!hasAnyAnswer){
    setLiveScoreVisibility(false);
    return;
  }

  setLiveScoreVisibility(true);
  if (quizCorrectCountEl) quizCorrectCountEl.textContent = String(correctCount);
  if (quizCurrentIndexEl) quizCurrentIndexEl.textContent = String(currentIndex + 1);
}

function startGlobalTimer(){
  if (totalTimer) clearInterval(totalTimer);
  ritualStartTime = Date.now();
  lastTotalSeconds = 0;
  totalTimer = setInterval(() => {
    lastTotalSeconds = Math.round((Date.now() - ritualStartTime) / 1000);
  }, 1000);
}
function clearQuestionTimer(){
  if (questionTimer){ clearInterval(questionTimer); questionTimer = null; }
}
function clearExplanationCountdown(){
  if (explanationCountdown){ clearInterval(explanationCountdown); explanationCountdown = null; }
}

function startQuestionTimer(){
  try{ voResetTimerRing(); }catch(e){}
  clearQuestionTimer();
  clearExplanationCountdown();

  const signature = isSignatureIndex(currentIndex);
  const seconds = 60;

  questionRemaining = seconds;

  railTotalSeconds = seconds;
  setRailMode("question");
  setRailProgress(questionRemaining, railTotalSeconds);

  setTimerMode("question");
  if (quizTimerEl) quizTimerEl.textContent = `Temps · ${formatSeconds(questionRemaining)}`;

  questionTimer = setInterval(() => {
    questionRemaining -= 1;
    setRailProgress(questionRemaining, railTotalSeconds);

    if (questionRemaining <= 0){
      questionRemaining = 0;
      if (quizTimerEl) quizTimerEl.textContent = `Temps · ${formatSeconds(0)}`;
      setRailProgress(0, railTotalSeconds);
      clearQuestionTimer();
      autoValidateOnTimeout();
    } else {
      if (quizTimerEl) quizTimerEl.textContent = `Temps · ${formatSeconds(questionRemaining)}`;
    }
  }, 1000);
}

function startRituel(){
  currentIndex = 0;
  answers = [];
  pendingAnswer = null;
  currentSelection = null;
  showingExplanation = false;
  ritualFinished = false;
  finalPayload = null;

  correctCount = 0;

  hasAnyAnswer = false;
  try { setLiveScoreVisibility(false); } catch(e) {}

  clearQuestionTimer();
  clearExplanationCountdown();
  startGlobalTimer();
  renderQuestion();
}

function renderQuestion(){
  const q = QUIZ_DATA[currentIndex];

  if (quizQuestionEl) quizQuestionEl.textContent = velvetNormalize(q.question);
  try{ voEnsureTimerRing(); }catch(e){}
  if (quizMetaEl) quizMetaEl.textContent = `Domaine : ${q.domain}`;
  if (quizIndexEl) quizIndexEl.textContent = String(currentIndex + 1);
  if (quizTotalEl) quizTotalEl.textContent = String(TOTAL_QUESTIONS);

  setSignatureUI(isSignatureIndex(currentIndex));

  showingExplanation = false;
  if (quizExplanationEl){
    quizExplanationEl.classList.add("hidden");
    quizExplanationEl.innerHTML = "";
  }
  pendingAnswer = null;

  clearExplanationCountdown();

  currentShuffle = shuffleArray([0,1,2,3]);

  optionButtons.forEach((btn, displayIndex) => {
    const realIndex = currentShuffle[displayIndex];
    btn.dataset.displayIndex = String(displayIndex);
    btn.dataset.realIndex = String(realIndex);

    const txt = btn.querySelector(".quiz-option-text");
    if (txt) txt.textContent = velvetNormalize(q.options[realIndex] ?? "");

    btn.classList.remove("selected","disabled","correct","wrong","timeout","shake");
  });

  const wrap = document.getElementById("quiz-options");
  if (wrap) wrap.classList.remove("veil");

  currentSelection = null;
  if (btnNext){
    btnNext.disabled = true;
    btnNext.textContent = (currentIndex === TOTAL_QUESTIONS - 1) ? "Terminer le rituel" : "Valider la réponse";
  }

  updateCorrectCounter();
  startQuestionTimer();
}

optionButtons.forEach(btn => {
  btn.addEventListener("click", (e) => {
    primeTickAudio();
    if (showingExplanation) return;
    spawnRipple(btn, e);

    const displayIndex = parseInt(btn.dataset.displayIndex, 10);
    const realIndex = parseInt(btn.dataset.realIndex, 10);

    currentSelection = { displayIndex, actualIndex: realIndex };

    optionButtons.forEach(b => b.classList.remove("selected"));
    btn.classList.add("selected");
    if (btnNext) btnNext.disabled = false;
  });
});

function advanceFromExplanation(){
  if (!showingExplanation) return;

  showingExplanation = false;
  clearExplanationCountdown();
  setTimerMode("question");

  if (pendingAnswer){
    answers.push(pendingAnswer);
    pendingAnswer = null;
  }

  if (currentIndex < TOTAL_QUESTIONS - 1){
    currentIndex += 1;
    renderQuestion();
  } else {
    endRituel();
  }

  updateCorrectCounter();
}

function resolveCurrentQuestion(forceTimeout=false){
  if (showingExplanation) return;

  clearQuestionTimer();
  clearExplanationCountdown();

  const q = QUIZ_DATA[currentIndex];

  let choiceIndex, choiceLetter, userText;
  let isTimeout = false;

  if (!currentSelection || forceTimeout){
    choiceIndex = -1;
    choiceLetter = "-";
    userText = "Aucune réponse (temps écoulé)";
    isTimeout = true;
  } else {
    choiceIndex = currentSelection.actualIndex;
    choiceLetter = LETTERS[currentSelection.displayIndex];
    userText = q.options[choiceIndex];
  }

  const correctIndex = q.correct_index;
  const correctDisplayIndex = currentShuffle.indexOf(correctIndex);
  const correctLetter = LETTERS[correctDisplayIndex];
  const correctText = q.options[correctIndex];

  const isCorrect = !isTimeout && (choiceIndex === correctIndex);

  if (!hasAnyAnswer) hasAnyAnswer = true;

  if (isCorrect) correctCount += 1;
  updateCorrectCounter();

  let resultLabel = "";
  let resultClass = "";
  if (isTimeout){
    resultLabel = "Réponse enregistrée (temps écoulé)";
    resultClass = "timeout";
  }
  else if (isCorrect){
    resultLabel = "Réponse validée";
    resultClass = "good";
  }
  else {
    resultLabel = "Réponse non retenue";
    resultClass = "bad";
  }

  if (quizExplanationEl){
    quizExplanationEl.innerHTML = `
      <div class="quiz-explanation-line ex-user">
        <span class="ex-label">Ta réponse</span>
        <span class="letter">${choiceLetter}</span>
        <span class="text"> — ${velvetNormalize(userText)}</span>
      </div>
      <div class="quiz-explanation-line ex-result ${resultClass}">
        ${resultLabel}
      </div>
      <div class="quiz-explanation-line ex-correct">
        <span class="ex-label">Réponse attendue</span>
        <span class="letter">${correctLetter}</span>
        <span class="text"> — ${velvetNormalize(correctText)}</span>
      </div>
      ${q.explanation ? `<div class="quiz-explanation-line ex-orion">${velvetNormalize(q.explanation)}</div>` : ""}
    `;
    quizExplanationEl.classList.remove("hidden");
  }

  optionButtons.forEach(b => b.classList.add("disabled"));
  showingExplanation = true;

  optionButtons.forEach(b => b.classList.remove("correct","wrong","timeout","shake"));

  const selectedDisplay = currentSelection ? currentSelection.displayIndex : null;

  performVerdictReveal(correctDisplayIndex, () => {
    if (isTimeout){
      const correctBtn = optionButtons[correctDisplayIndex];
      if (correctBtn) correctBtn.classList.add("correct");
      optionButtons.forEach(b => b.classList.add("timeout"));
    } else {
      const selectedBtn = (selectedDisplay !== null) ? optionButtons[selectedDisplay] : null;
      const correctBtn = optionButtons[correctDisplayIndex];

      if (isCorrect){
        if (selectedBtn) selectedBtn.classList.add("correct");
      } else {
        if (selectedBtn){
          selectedBtn.classList.add("wrong","shake");
          setTimeout(() => selectedBtn.classList.remove("shake"), 220);
        }
        if (correctBtn) correctBtn.classList.add("correct");
      }
    }
  });

  if (btnNext){
    btnNext.textContent = (currentIndex === TOTAL_QUESTIONS - 1) ? "Terminer le rituel" : "Question suivante";
    btnNext.disabled = false;
  }

  pendingAnswer = { question_id: q.id, choice_index: choiceIndex, choice_letter: choiceLetter };

  const signature = isSignatureIndex(currentIndex);
  explanationRemaining = 60;

  railTotalSeconds = explanationRemaining;
  setRailMode("lecture");
  setRailProgress(explanationRemaining, railTotalSeconds);

  setTimerMode("lecture");
  if (quizTimerEl) quizTimerEl.textContent = `Lecture · ${formatSeconds(explanationRemaining)}`;

  clearExplanationCountdown();
  explanationCountdown = setInterval(() => {
    explanationRemaining -= 1;
    setRailProgress(explanationRemaining, railTotalSeconds);

    if (explanationRemaining <= 0){
      explanationRemaining = 0;
      if (quizTimerEl) quizTimerEl.textContent = `Lecture · ${formatSeconds(0)}`;
      setRailProgress(0, railTotalSeconds);
      clearExplanationCountdown();
      if (showingExplanation && !ritualFinished) advanceFromExplanation();
    } else {
      if (quizTimerEl) quizTimerEl.textContent = `Lecture · ${formatSeconds(explanationRemaining)}`;
    }
  }, 1000);
}

function autoValidateOnTimeout(){
  if (!showingExplanation){
    if (currentSelection) resolveCurrentQuestion(false);
    else resolveCurrentQuestion(true);
  }
}

if (btnNext) {
  btnNext.addEventListener("click", () => {
    primeTickAudio();
    if (!showingExplanation){
      if (!currentSelection) return;
      resolveCurrentQuestion(false);
      return;
    }
    advanceFromExplanation();
  });
}

function endRituel(){
  if (totalTimer){ clearInterval(totalTimer); totalTimer = null; }
  clearQuestionTimer();
  clearExplanationCountdown();

  finalTotalSeconds = lastTotalSeconds;

  finalScore = 0;
  finalEnrichedAnswers = answers.map((a, i) => {
    const q = QUIZ_DATA.find(qq => String(qq.id) === String(a.question_id));

    const correct_index = (q && Number.isFinite(Number(q.correct_index))) ? Number(q.correct_index) : null;
    const selected_index = (a && Number.isFinite(Number(a.choice_index))) ? Number(a.choice_index) : (a?.choice_index === -1 ? -1 : null);

    const is_timeout = (selected_index === -1);
    const is_correct = (!is_timeout && correct_index !== null && selected_index === correct_index);

    const status = is_timeout ? "timeout" : (is_correct ? "correct" : "wrong");
    if (is_correct) finalScore += 1;

    return {
      q: i + 1,
      question_id: a.question_id,
      selected_index,
      selected_letter: a.choice_letter || null, // lettre affichée côté UI (après shuffle)
      correct_index,
      correct_letter: (correct_index === 0 || correct_index === 1 || correct_index === 2 || correct_index === 3) ? LETTERS[correct_index] : null,
      status,
      is_correct
    };
  });

  ritualFinished = true;

  let verdictTitle, verdictSubtitle;
  if (finalScore >= 12){
    verdictTitle = "Parcours observé";
    verdictSubtitle = "Ce rituel apporte des éléments d’observation sur ton parcours.";
  } else {
    verdictTitle = "Parcours enregistré";
    verdictSubtitle = "Chaque rituel constitue un instant dans le temps.";
  }

  if (resultTitleEl) resultTitleEl.textContent = verdictTitle;
  if (resultSubtitleEl) resultSubtitleEl.textContent = verdictSubtitle;
  if (resultScoreEl) resultScoreEl.textContent = `${finalScore} / ${TOTAL_QUESTIONS}`;
  if (resultTimeEl) resultTimeEl.textContent = formatSeconds(finalTotalSeconds);

  // ✅ Stop forcing expand outside the ritual screen (mobile usability)
  VO_AUTO_EXPAND_ENABLED = false;

  if (screenQuiz) screenQuiz.classList.add("hidden");
  if (screenResult) screenResult.classList.remove("hidden");
}

if (btnGoFeedback) {
  btnGoFeedback.addEventListener("click", () => {
    primeTickAudio();
    VO_AUTO_EXPAND_ENABLED = false;
    if (screenResult) screenResult.classList.add("hidden");
    if (screenFeedbackFinal) screenFeedbackFinal.classList.remove("hidden");
  });
}

if (feedbackFinalSendBtn && feedbackFinalTextEl) {
  feedbackFinalSendBtn.disabled = true;
  feedbackFinalTextEl.addEventListener("input", () => {
    feedbackFinalSendBtn.disabled = (feedbackFinalTextEl.value.trim().length === 0);
  });
}

if (feedbackFinalSendBtn) {
  feedbackFinalSendBtn.addEventListener("click", async () => {
    primeTickAudio();
    if (feedbackFinalSendBtn.disabled) return;

    const feedbackText = feedbackFinalTextEl.value.trim();

    finalPayload = {
      mode: "rituel_full_v1",
      score: finalScore,
      total: TOTAL_QUESTIONS,
      time_spent_seconds: finalTotalSeconds,
      time_total_seconds: finalTotalSeconds,
      time_formatted: formatSeconds(finalTotalSeconds),
      answers: finalEnrichedAnswers,
      comment_text: feedbackText,
      analysis_mode: "nova_writing_score_v1"
    };

    // ✅ Attach attempt_id + telegram_user_id to the Telegram sendData payload
    // This allows the bot (WEB_APP_DATA handler) to link feedback to the correct attempt in Airtable.
    // (HTTP /ritual/complete already receives attempt_id, but sendData previously did not.)
    finalPayload.attempt_id = ritualAttemptId || null;
    finalPayload.attempt_record_id = ritualAttemptId || null; // alias for server-side compatibility
    finalPayload.telegram_user_id = ritualPlayerTelegramUserId || getTelegramUserId() || null;


    // ✅ 1) HTTP complete (Network visible)
    if (!finalPayloadHttpSent) {
      try {
        await ensureAttemptStarted();
        await postRitualComplete(finalPayload);
        finalPayloadHttpSent = true;
      } catch (e) {
        console.error("❌ HTTP complete failed (feedback stage):", e?.message || e);
      }
    }

    // ✅ 2) Telegram sendData (bot)
    console.log("🔍 DEBUG - window.Telegram exists:", !!window.Telegram);
    console.log("🔍 DEBUG - window.Telegram.WebApp exists:", !!window.Telegram?.WebApp);
    console.log("🔍 DEBUG - sendData exists:", !!window.Telegram?.WebApp?.sendData);
    console.log("🔍 DEBUG - finalPayload:", finalPayload);
    
    try {
      if (!window.Telegram || !window.Telegram.WebApp || !window.Telegram.WebApp.sendData) {
        throw new Error("Telegram WebApp API not available");
      }
      window.Telegram.WebApp.sendData(JSON.stringify(finalPayload));
      finalPayloadSent = true;
      console.log("✅ sendData() envoyé (feedback) — payload_len =", JSON.stringify(finalPayload).length);
    } catch (e) {
      console.error("❌ sendData() a échoué (feedback) :", e);
      console.error("❌ Error details:", e.message, e.stack);
    }

    feedbackFinalSendBtn.disabled = true;
    if (feedbackFinalTextEl) feedbackFinalTextEl.readOnly = true;
    feedbackFinalSendBtn.classList.add("hidden");

    if (feedbackFinalMessageEl){
      feedbackFinalMessageEl.classList.remove("hidden");
      feedbackFinalMessageEl.innerHTML = `
        Merci. Ton passage est inscrit.<br><br>
        Certains rituels ferment un cycle. Celui-ci en ouvre un autre — plus discret, plus exigeant.<br><br>
        Si un jour ton nom doit revenir dans nos cercles, ce sera naturellement.
      `;
    }
    if (feedbackFinalSignatureEl) feedbackFinalSignatureEl.classList.remove("hidden");
    if (feedbackFinalCloseBtn) {
      feedbackFinalCloseBtn.disabled = false;
      feedbackFinalCloseBtn.classList.remove("hidden");
    }
  });
}

if (feedbackFinalCloseBtn) {
  feedbackFinalCloseBtn.addEventListener("click", async () => {
    primeTickAudio();
    if (!finalPayload) return;

    // ✅ fallback HTTP si jamais non parti
    if (!finalPayloadHttpSent) {
      try {
        await ensureAttemptStarted();
        await postRitualComplete(finalPayload);
        finalPayloadHttpSent = true;
      } catch (e) {
        console.error("❌ HTTP complete failed (close fallback):", e?.message || e);
      }
    }

    // ✅ fallback Telegram si jamais non parti
    if (!finalPayloadSent) {
      console.log("🔍 DEBUG (fallback) - window.Telegram exists:", !!window.Telegram);
      console.log("🔍 DEBUG (fallback) - window.Telegram.WebApp exists:", !!window.Telegram?.WebApp);
      console.log("🔍 DEBUG (fallback) - sendData exists:", !!window.Telegram?.WebApp?.sendData);
      
      try {
        if (!window.Telegram || !window.Telegram.WebApp || !window.Telegram.WebApp.sendData) {
          throw new Error("Telegram WebApp API not available");
        }
        window.Telegram.WebApp.sendData(JSON.stringify(finalPayload));
        finalPayloadSent = true;
        console.log("✅ sendData() envoyé (close fallback) — payload_len =", JSON.stringify(finalPayload).length);
      } catch (e) {
        console.error("❌ sendData() a échoué (close fallback) :", e);
        console.error("❌ Error details:", e.message, e.stack);
      }
    }

    try { window.Telegram?.WebApp?.close?.(); } catch (e) {
      console.warn("⚠️ close() indisponible :", e);
    }
  });
}

console.log("✅ Listeners OK — boutons connectés");