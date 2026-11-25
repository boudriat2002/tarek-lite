import base64
import hashlib
import html
import os
import re
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit
from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

DEFAULT_CDN_HOST = "z-m-video.falg2-2.fna.fbcdn.net"

# على Render المجلد المؤقت /tmp هو المسموح بالكتابة فيه (ويُمسح عند إعادة التشغيل)
STORAGE_DIR = os.environ.get("STORAGE_DIR", "/tmp/offline_videos")
os.makedirs(STORAGE_DIR, exist_ok=True)

# أقصى حجم للحفظ بالكاش (بالميغابايت) لحماية مساحة السيرفر المجاني
MAX_SAVE_MB = int(os.environ.get("MAX_SAVE_MB", "150"))
MAX_SAVE_BYTES = MAX_SAVE_MB * 1024 * 1024

FB_WEBVIEW_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; DevHilal Build/HUAWEIDRA-Hilal; wv) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/88.0.4324.93 "
        "Mobile Safari/537.36 [FBAN/EMA;FBLC/ar_AR;FB_WAB/368.0.0.5.95]"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar-DZ,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

EXO_VIDEO_HEADERS = {
    "User-Agent": "exoplayer_video",
    "Connection": "keep-alive",
    "Accept-Encoding": "identity",
}


def create_pooled_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=32,
        pool_maxsize=32,
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# جلسة اتصال دائمة لتسريع الجلب ومنع تقطيع البث عند طلب أجزاء الفيديو (Range Requests)
GLOBAL_SESSION = create_pooled_session()


# ---------------------------------------------------------------------------
# حماية: السيرفر أصبح عاماً على الإنترنت، لذلك نسمح فقط بنطاقات فيسبوك
# حتى لا يتحول إلى بروكسي مفتوح يستغله أي شخص.
# ---------------------------------------------------------------------------
def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_allowed_media_host(url: str) -> bool:
    host = _host_of(url)
    return host == "fbcdn.net" or host.endswith(".fbcdn.net")


def is_allowed_page_host(url: str) -> bool:
    host = _host_of(url)
    allowed = ("facebook.com", "fb.watch", "fb.com", "fb.me")
    return any(host == d or host.endswith("." + d) for d in allowed)


HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>TAREK 0 LITE — مشغل الفيديو السريع</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #050507;
      --surface: rgba(15, 17, 23, 0.88);
      --surface-2: #141720;
      --border: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(244, 63, 94, 0.55);
      --primary: #f43f5e;
      --primary-dark: #be123c;
      --primary-glow: rgba(244, 63, 94, 0.25);
      --cyan: #06b6d4;
      --emerald: #10b981;
      --amber: #f59e0b;
      --violet: #8b5cf6;
      --text: #f8fafc;
      --muted: #94a3b8;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      font-family: 'Tajawal', system-ui, -apple-system, sans-serif;
    }

    body {
      min-height: 100vh;
      background-color: var(--bg);
      background-image:
        radial-gradient(circle at 15% 10%, rgba(244, 63, 94, 0.16), transparent 40%),
        radial-gradient(circle at 85% 90%, rgba(139, 92, 246, 0.12), transparent 45%);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 18px;
    }

    .container {
      width: 100%;
      max-width: 860px;
      background: var(--surface);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid var(--border);
      border-radius: 26px;
      padding: 26px;
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.85), inset 0 1px 0 rgba(255, 255, 255, 0.06);
    }

    .header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 18px;
      margin-bottom: 20px;
      border-bottom: 1px solid var(--border);
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-icon {
      width: 42px;
      height: 42px;
      border-radius: 13px;
      background: linear-gradient(135deg, var(--primary), var(--primary-dark));
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      box-shadow: 0 8px 24px var(--primary-glow);
      flex-shrink: 0;
    }

    .brand-text h1 {
      font-size: 1.25rem;
      font-weight: 800;
      letter-spacing: 0.2px;
      color: #ffffff;
      line-height: 1.2;
    }

    .brand-text span {
      font-size: 0.8rem;
      color: var(--muted);
    }

    .badge-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.78rem;
      font-weight: 700;
      color: #fda4af;
      background: rgba(244, 63, 94, 0.12);
      border: 1px solid rgba(244, 63, 94, 0.3);
      padding: 6px 12px;
      border-radius: 999px;
      white-space: nowrap;
    }

    .pulse-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--primary);
      box-shadow: 0 0 8px var(--primary);
      animation: pulse 1.8s infinite;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(0.85); }
    }

    .input-box {
      position: relative;
      margin-bottom: 16px;
    }

    textarea {
      width: 100%;
      min-height: 74px;
      background: rgba(6, 7, 10, 0.85);
      color: #f1f5f9;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px 16px 14px 44px;
      direction: ltr;
      text-align: left;
      font-size: 0.88rem;
      line-height: 1.5;
      resize: vertical;
      transition: all 0.2s ease;
    }

    textarea:focus {
      outline: none;
      border-color: var(--border-focus);
      box-shadow: 0 0 0 4px rgba(244, 63, 94, 0.14);
    }

    .paste-btn {
      position: absolute;
      left: 10px;
      top: 10px;
      background: var(--surface-2);
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 10px;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .paste-btn:hover {
      color: #fff;
      border-color: rgba(255, 255, 255, 0.2);
    }

    .actions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }

    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border: none;
      border-radius: 14px;
      padding: 12px 14px;
      font-weight: 700;
      font-size: 0.88rem;
      cursor: pointer;
      transition: all 0.18s ease;
      white-space: nowrap;
    }

    .btn svg {
      width: 18px;
      height: 18px;
      flex-shrink: 0;
    }

    .btn:hover {
      transform: translateY(-1px);
    }

    .btn:active {
      transform: scale(0.98);
    }

    .btn-primary {
      background: linear-gradient(135deg, var(--primary), var(--primary-dark));
      color: #fff;
      box-shadow: 0 8px 22px var(--primary-glow);
    }

    .btn-download {
      background: rgba(16, 185, 129, 0.14);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.35);
    }
    .btn-download:hover {
      background: rgba(16, 185, 129, 0.22);
    }

    .btn-pip {
      background: rgba(139, 92, 246, 0.15);
      color: #c4b5fd;
      border: 1px solid rgba(139, 92, 246, 0.35);
    }
    .btn-pip:hover {
      background: rgba(139, 92, 246, 0.24);
    }

    .btn-save {
      background: rgba(245, 158, 11, 0.14);
      color: #fcd34d;
      border: 1px solid rgba(245, 158, 11, 0.35);
    }
    .btn-save:hover {
      background: rgba(245, 158, 11, 0.22);
    }

    .btn-ghost {
      background: var(--surface-2);
      color: #cbd5e1;
      border: 1px solid var(--border);
    }
    .btn-ghost:hover {
      background: #1c202c;
    }

    .status {
      display: none;
      align-items: center;
      gap: 10px;
      padding: 12px 15px;
      border-radius: 14px;
      font-size: 0.88rem;
      margin-bottom: 18px;
      line-height: 1.5;
      word-break: break-word;
    }

    .status.info {
      display: flex;
      background: rgba(6, 182, 212, 0.12);
      color: #a5f3fc;
      border: 1px solid rgba(6, 182, 212, 0.3);
    }

    .status.error {
      display: flex;
      background: rgba(239, 68, 68, 0.15);
      color: #fca5a5;
      border: 1px solid rgba(239, 68, 68, 0.35);
    }

    .status.ok {
      display: flex;
      background: rgba(16, 185, 129, 0.14);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.35);
    }

    .spinner {
      width: 17px;
      height: 17px;
      border: 2px solid currentColor;
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.75s linear infinite;
      flex-shrink: 0;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    .player-wrapper {
      position: relative;
      background: #000;
      border: 1px solid var(--border);
      border-radius: 20px;
      overflow: hidden;
      margin-bottom: 18px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.85);
    }

    video {
      display: block;
      width: 100%;
      max-height: 510px;
      background: #000;
    }

    .quality-bar {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .label-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.85rem;
      color: var(--muted);
      font-weight: 600;
    }

    .label-title {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    select {
      width: 100%;
      background: rgba(6, 7, 10, 0.9);
      color: #f1f5f9;
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 14px;
      direction: ltr;
      text-align: left;
      font-size: 0.86rem;
      cursor: pointer;
      transition: border-color 0.2s ease;
    }

    select:focus {
      outline: none;
      border-color: var(--border-focus);
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="brand">
        <div class="brand-icon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5.14v14l11-7-11-7z"/>
          </svg>
        </div>
        <div class="brand-text">
          <h1>TAREK 0 LITE</h1>
          <span>بث مباشر فائق السرعة بدون تقطيع</span>
        </div>
      </div>
      <div class="badge-pill">
        <span class="pulse-dot"></span>
        <span>ULTRA STREAM</span>
      </div>
    </div>

    <div class="input-box">
      <textarea id="fbInput" placeholder="الصق رابط الفيديو هنا..."></textarea>
      <button class="paste-btn" type="button" onclick="pasteFromClipboard()" title="لصق من الحافظة">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
        </svg>
      </button>
    </div>

    <div class="actions-grid">
      <button class="btn btn-primary" type="button" onclick="generateAndPlay()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="5 3 19 12 5 21 5 3"></polygon>
        </svg>
        <span>تشغيل فوري</span>
      </button>

      <button class="btn btn-download" type="button" onclick="downloadDirectVideo()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="7 10 12 15 17 10"></polyline>
          <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        <span>تحميل الفيديو</span>
      </button>

      <button class="btn btn-pip" type="button" onclick="toggleBackgroundPlay()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect>
          <rect x="12" y="9" width="8" height="6" rx="1" fill="currentColor"></rect>
        </svg>
        <span>مشاهدة في الخلفية</span>
      </button>

      <button class="btn btn-save" type="button" onclick="saveOffline()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
          <polyline points="17 21 17 13 7 13 7 21"></polyline>
          <polyline points="7 3 7 8 15 8"></polyline>
        </svg>
        <span>حفظ بالكاش</span>
      </button>

      <button class="btn btn-ghost" type="button" onclick="clearAll()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
          <path d="M10 11v6"></path>
          <path d="M14 11v6"></path>
        </svg>
        <span>مسح</span>
      </button>
    </div>

    <div id="status" class="status" role="status" aria-live="polite"></div>

    <div class="player-wrapper">
      <video id="player" controls playsinline preload="auto"></video>
    </div>

    <div class="quality-bar">
      <div class="label-row">
        <span class="label-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="4" y1="21" x2="4" y2="14"></line>
            <line x1="4" y1="10" x2="4" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="12"></line>
            <line x1="12" y1="8" x2="12" y2="3"></line>
            <line x1="20" y1="21" x2="20" y2="16"></line>
            <line x1="20" y1="12" x2="20" y2="3"></line>
          </svg>
          <span>الجودات والروابط المستخرجة:</span>
        </span>
        <span id="countBadge">0 روابط</span>
      </div>
      <select id="candidatesSelect" onchange="onCandidateChange()">
        <option value="">— بانتظار إدخال الرابط —</option>
      </select>
    </div>
  </div>

  <script>
    const fbInput = document.getElementById("fbInput");
    const statusEl = document.getElementById("status");
    const player = document.getElementById("player");
    const candidatesSelect = document.getElementById("candidatesSelect");
    const countBadge = document.getElementById("countBadge");

    let candidatesList = [];
    let currentFullUrl = "";
    let currentOrigUrl = "";

    function showStatus(type, msg, loading = false) {
      statusEl.className = "status " + type;
      statusEl.innerHTML = loading
        ? `<span class="spinner"></span><span>${msg}</span>`
        : `<span>${msg}</span>`;
    }

    async function pasteFromClipboard() {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          fbInput.value = text.trim();
          generateAndPlay();
        }
      } catch {
        showStatus("info", "اضغط مطولاً داخل مربع النص واختر لصق.");
      }
    }

    function formatDuration(sec) {
      if (!sec || sec <= 0) return "غير محددة";
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
      return `${m}:${String(s).padStart(2, "0")}`;
    }

    function setupMediaSession(titleText) {
      if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: titleText || "TAREK 0 LITE Video",
          artist: "TAREK 0 LITE Stream",
        });
        navigator.mediaSession.setActionHandler("play", () => player.play());
        navigator.mediaSession.setActionHandler("pause", () => player.pause());
        navigator.mediaSession.setActionHandler("seekbackward", () => {
          player.currentTime = Math.max(0, player.currentTime - 10);
        });
        navigator.mediaSession.setActionHandler("seekforward", () => {
          player.currentTime = Math.min(player.duration || 0, player.currentTime + 10);
        });
      }
    }

    function startPlayerWithSrc(srcUrl, msg) {
      player.pause();
      player.src = srcUrl;
      player.load();
      setupMediaSession("فيديو TAREK 0 LITE");

      player.addEventListener("canplay", async () => {
        try {
          await player.play();
          showStatus("ok", msg || "يتم التشغيل الآن بسلاسة.");
        } catch (e) {
          if (e.name !== "AbortError") {
            showStatus("info", "الفيديو جاهز؛ اضغط على زر التشغيل في المشغل.");
          }
        }
      }, { once: true });
    }

    function applyCandidateAt(index, autoPlay = true) {
      const item = candidatesList[index];
      if (!item) return;
      currentFullUrl = item.full_url;
      currentOrigUrl = item.orig_url;

      if (autoPlay) {
        const durText = formatDuration(item.duration_s);
        const streamUrl = `/stream?u=${encodeURIComponent(currentFullUrl)}&orig=${encodeURIComponent(currentOrigUrl)}`;
        startPlayerWithSrc(streamUrl, `جاري العرض — المدة: ${durText} (${item.tag_hint})`);
      }
    }

    function onCandidateChange() {
      const idx = parseInt(candidatesSelect.value, 10);
      if (!Number.isNaN(idx)) applyCandidateAt(idx, true);
    }

    async function generateAndPlay() {
      const url = fbInput.value.trim();
      if (!url) return showStatus("error", "الرجاء لصق رابط الفيديو أولاً.");

      showStatus("info", "جاري استخراج الفيديو بأقصى سرعة...", true);
      candidatesSelect.innerHTML = '<option value="">جاري الجلب...</option>';
      countBadge.textContent = "...";
      candidatesList = [];
      currentFullUrl = "";
      currentOrigUrl = "";
      player.pause();
      player.removeAttribute("src");
      player.load();

      try {
        const res = await fetch("/api/convert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url })
        });
        const data = await res.json();

        if (!res.ok || !Array.isArray(data.candidates) || data.candidates.length === 0) {
          throw new Error(data.error || "تعذر استخراج رابط الفيديو.");
        }

        candidatesList = data.candidates;
        countBadge.textContent = `${candidatesList.length} روابط`;
        candidatesSelect.innerHTML = candidatesList.map((c, i) => {
          const durStr = formatDuration(c.duration_s);
          const previewTag = c.is_preview ? " [معاينة]" : "";
          return `<option value="${i}">[${i + 1}] المدة: ${durStr}${previewTag} — ${c.tag_hint}</option>`;
        }).join("");

        const bestIdx = typeof data.best_index === "number" ? data.best_index : 0;
        candidatesSelect.value = String(bestIdx);
        applyCandidateAt(bestIdx, true);
      } catch (err) {
        candidatesSelect.innerHTML = '<option value="">— لا توجد روابط —</option>';
        countBadge.textContent = "0 روابط";
        showStatus("error", err.message);
      }
    }

    async function downloadDirectVideo() {
      if (!currentFullUrl && !currentOrigUrl) {
        const rawUrl = fbInput.value.trim();
        if (!rawUrl) return showStatus("error", "أدخل رابط الفيديو وشغّله أولاً ليتم تحميله.");
        await generateAndPlay();
        if (!currentFullUrl && !currentOrigUrl) return;
      }

      showStatus("ok", "بدأ تحميل ملف الفيديو إلى جهازك...");
      const dlUrl = `/download?u=${encodeURIComponent(currentFullUrl)}&orig=${encodeURIComponent(currentOrigUrl)}`;
      const a = document.createElement("a");
      a.href = dlUrl;
      a.download = "TAREK_0_LITE_VIDEO.mp4";
      document.body.appendChild(a);
      a.click();
      a.remove();
    }

    async function toggleBackgroundPlay() {
      if (!player.src) {
        return showStatus("error", "قم بتشغيل الفيديو أولاً لتفعيل المشاهدة في الخلفية.");
      }
      try {
        if (document.pictureInPictureElement) {
          await document.exitPictureInPicture();
          showStatus("info", "تم إغلاق نافذة المشاهدة العائمة.");
        } else if (document.pictureInPictureEnabled && !player.disablePictureInPicture) {
          if (player.paused) await player.play();
          await player.requestPictureInPicture();
          showStatus("ok", "وضع المشاهدة في الخلفية (نافذة عائمة) نشط الآن.");
        } else if (player.webkitSetPresentationMode) {
          const mode = player.webkitPresentationMode === "picture-in-picture" ? "inline" : "picture-in-picture";
          player.webkitSetPresentationMode(mode);
          showStatus("ok", "تم تفعيل وضع المشاهدة في الخلفية.");
        } else {
          if (player.paused) await player.play();
          showStatus("info", "تم تفعيل تشغيل الصوت في الخلفية عند تصغير المتصفح.");
        }
      } catch (err) {
        showStatus("error", "تعذر فتح النافذة العائمة: تأكد من بدء تشغيل الفيديو أولاً.");
      }
    }

    async function saveOffline() {
      const sourceLink = fbInput.value.trim();
      if (!currentFullUrl && !currentOrigUrl && !sourceLink) {
        return showStatus("error", "أدخل رابط الفيديو أولاً.");
      }
      showStatus("info", "جاري حفظ نسخة في ذاكرة الخادم المحلية...", true);
      try {
        const res = await fetch("/api/save_offline", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            url: sourceLink,
            full_url: currentFullUrl,
            orig_url: currentOrigUrl
          })
        });
        const data = await res.json();
        if (!res.ok || !data.local_url) throw new Error(data.error || "تعذر حفظ الفيديو محلياً.");
        startPlayerWithSrc(data.local_url, "تم الحفظ على الخادم — التشغيل يتم الآن من النسخة المحفوظة.");
      } catch (err) {
        showStatus("error", err.message);
      }
    }

    player.addEventListener("error", () => {
      if (!player.getAttribute("src")) return;
      const code = player.error ? player.error.code : "unknown";
      showStatus("error", `حدث خطأ في البث (رمز: ${code}). اختر رابطاً آخر من القائمة بالأسفل.`);
    });

    function clearAll() {
      if (document.pictureInPictureElement) {
        document.exitPictureInPicture().catch(() => {});
      }
      fbInput.value = "";
      currentFullUrl = "";
      currentOrigUrl = "";
      candidatesList = [];
      candidatesSelect.innerHTML = '<option value="">— بانتظار إدخال الرابط —</option>';
      countBadge.textContent = "0 روابط";
      player.pause();
      player.removeAttribute("src");
      player.load();
      statusEl.className = "status";
      statusEl.textContent = "";
    }
  </script>
</body>
</html>
"""


def normalize_to_host(mp4_url: str, cdn_host: str = DEFAULT_CDN_HOST) -> str:
    parts = urlsplit(mp4_url.strip())
    host = cdn_host.strip() or DEFAULT_CDN_HOST
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def split_url_and_params(full_url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(full_url)
    base_url = urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))
    raw_pairs = parse_qs(parts.query, keep_blank_values=True)
    params_dict = {k: v[0] if v else "" for k, v in raw_pairs.items()}
    return base_url, params_dict


def is_preview_candidate(url: str) -> bool:
    low = url.lower()
    return any(tok in low for tok in ("sve_sd", "sve_hd", "preview", "thumbnail", "story_preview"))


def extract_duration_s(url: str) -> int:
    parsed = urlsplit(url)
    qs = parse_qs(parsed.query)
    raw_efg = qs.get("efg", [""])[0]
    if not raw_efg:
        return 0
    decoded_efg = unquote(raw_efg).strip()
    padded = decoded_efg + ("=" * ((4 - len(decoded_efg) % 4) % 4))
    for fn in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw_bytes = fn(padded)
            text = raw_bytes.decode("utf-8", errors="ignore")
            m = re.search(r'"duration_s"\s*:\s*(\d+)', text)
            if m:
                return int(m.group(1))
        except Exception:
            continue
    return 0


def extract_bitrate(url: str) -> int:
    m = re.search(r'[?&]bitrate=(\d+)', url)
    return int(m.group(1)) if m else 0


def detect_tag_hint(url: str) -> str:
    m = re.search(r'[?&]tag=([^&]+)', url)
    if m:
        return m.group(1)
    if "progressive" in url:
        return "progressive"
    if "dash" in url:
        return "dash"
    return "mp4"


def candidate_sort_key(url: str) -> tuple[int, int, int, int]:
    non_preview = 0 if is_preview_candidate(url) else 1
    dur = extract_duration_s(url)
    prog = 1 if "progressive" in url else 0
    br = extract_bitrate(url)
    return (non_preview, dur, prog, br)


def extract_media_urls_from_text(text: str) -> list[str]:
    normalized = text.replace("\\/", "/")
    try:
        normalized = normalized.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        pass
    normalized = html.unescape(normalized)

    mp4_matches = re.findall(r'https://[^\s"\'<>\\]+?\.mp4(?:\?[^\s"\'<>\\]*)?', normalized)
    json_video_matches = re.findall(
        r'"(?:video_url|playable_url|playable_url_quality_hd|browser_native_hd_url|browser_native_sd_url)"\s*:\s*"([^"]+)"',
        normalized,
    )
    cleaned_json = [u.replace("\\/", "/") for u in json_video_matches]
    all_urls = mp4_matches + cleaned_json
    return list(dict.fromkeys(u for u in all_urls if u.startswith("https://")))


def extract_candidates(media_url: str, cdn_host: str = DEFAULT_CDN_HOST) -> dict:
    raw_clean = media_url.strip()
    low_url = raw_clean.lower()

    if ".mp4" in low_url or "fbcdn.net" in low_url:
        if not is_allowed_media_host(raw_clean):
            raise ValueError("الرابط المباشر يجب أن يكون من fbcdn.net.")
        unique_matches = [raw_clean]
    else:
        if not is_allowed_page_host(raw_clean):
            raise ValueError("يُسمح فقط بروابط فيسبوك (facebook.com / fb.watch).")
        r1 = GLOBAL_SESSION.get(
            raw_clean,
            headers=FB_WEBVIEW_HEADERS,
            allow_redirects=True,
            timeout=(12, 20),
        )
        r1.raise_for_status()
        unique_matches = extract_media_urls_from_text(r1.text)

        if not unique_matches and r1.url != raw_clean and is_allowed_page_host(r1.url):
            r2 = GLOBAL_SESSION.get(r1.url, headers=FB_WEBVIEW_HEADERS, timeout=(12, 20))
            r2.raise_for_status()
            unique_matches = extract_media_urls_from_text(r2.text)

    # نُبقي فقط روابط fbcdn
    unique_matches = [u for u in unique_matches if is_allowed_media_host(u)]

    if not unique_matches:
        raise ValueError("لم يتم العثور على رابط فيديو مباشر في الصفحة.")

    ranked = sorted(unique_matches, key=candidate_sort_key, reverse=True)
    candidates = []
    for u in ranked:
        mapped_u = normalize_to_host(u, cdn_host=cdn_host)
        candidates.append({
            "orig_url": u,
            "full_url": mapped_u,
            "tag_hint": detect_tag_hint(u),
            "duration_s": extract_duration_s(u),
            "bitrate": extract_bitrate(u),
            "is_preview": is_preview_candidate(u),
        })

    return {
        "best_index": 0,
        "candidates": candidates,
    }


def fetch_video_upstream(full_url: str, range_header: str | None = None, timeout=(15, 45)) -> requests.Response:
    base_url, params_dict = split_url_and_params(full_url)
    req_headers = dict(EXO_VIDEO_HEADERS)
    if range_header:
        req_headers["Range"] = range_header

    return GLOBAL_SESSION.get(
        base_url,
        params=params_dict,
        headers=req_headers,
        stream=True,
        timeout=timeout,
    )


def url_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:16]


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/health")
def health():
    return "ok", 200


@app.route("/api/convert", methods=["POST"])
def api_convert():
    data = request.get_json(silent=True) or {}
    link = (data.get("url") or "").strip()
    if not link:
        return jsonify({"error": "الرابط فارغ."}), 400

    try:
        return jsonify(extract_candidates(link, cdn_host=DEFAULT_CDN_HOST))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def proxy_video_response(as_attachment: bool = False):
    u_param = (request.args.get("u") or "").strip()
    orig_param = (request.args.get("orig") or "").strip()
    candidates = [
        u for u in (u_param, orig_param)
        if u.startswith(("http://", "https://")) and is_allowed_media_host(u)
    ]
    if not candidates:
        return "Invalid URL", 400

    range_hdr = request.headers.get("Range")
    last_err = "Upstream unavailable"

    for target in candidates:
        try:
            upstream = fetch_video_upstream(target, range_header=range_hdr, timeout=(15, 45))
            if upstream.status_code < 400:
                ctype = upstream.headers.get("Content-Type", "video/mp4")
                if "text/html" in ctype or "application/json" in ctype:
                    upstream.close()
                    last_err = "URL returned HTML/JSON"
                    continue

                resp_headers = {
                    "Cache-Control": "public, max-age=3600",
                    "X-Accel-Buffering": "no",
                }
                for h in ("Content-Length", "Content-Range", "Accept-Ranges"):
                    if h in upstream.headers:
                        resp_headers[h] = upstream.headers[h]

                if as_attachment:
                    resp_headers["Content-Disposition"] = 'attachment; filename="TAREK_0_LITE_VIDEO.mp4"'

                def generate(up=upstream):
                    try:
                        # حجم 512KB لتدفق أسرع ومنع التقطيع أثناء المشاهدة
                        for chunk in up.iter_content(chunk_size=524288):
                            if chunk:
                                yield chunk
                    finally:
                        up.close()

                return Response(generate(), status=upstream.status_code, headers=resp_headers, mimetype=ctype)
            upstream.close()
            last_err = f"Status {upstream.status_code}"
        except requests.RequestException as e:
            last_err = str(e)

    return f"Stream failed: {last_err}", 502


@app.route("/stream")
def stream():
    return proxy_video_response(as_attachment=False)


@app.route("/download")
def download():
    return proxy_video_response(as_attachment=True)


@app.route("/api/save_offline", methods=["POST"])
def api_save_offline():
    data = request.get_json(silent=True) or {}
    source_url = (data.get("url") or "").strip()
    full_url = (data.get("full_url") or "").strip()
    orig_url = (data.get("orig_url") or "").strip()

    candidates = [
        u for u in (full_url, orig_url)
        if u.startswith(("http://", "https://")) and is_allowed_media_host(u)
    ]
    if not candidates and source_url:
        try:
            extracted = extract_candidates(source_url, cdn_host=DEFAULT_CDN_HOST)
            candidates = [extracted["candidates"][0]["full_url"], extracted["candidates"][0]["orig_url"]]
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    if not candidates:
        return jsonify({"error": "لا يوجد رابط لحفظه."}), 400

    key = url_key(source_url or candidates[0])
    filename = f"{key}.mp4"
    filepath = os.path.join(STORAGE_DIR, filename)
    temp_path = filepath + ".part"

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        return jsonify({"local_url": f"/media/{filename}", "cached": True})

    written = 0
    last_exc = None
    for target in candidates:
        try:
            with fetch_video_upstream(target, timeout=(15, 60)) as resp:
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "")
                if "text/html" in ctype or "application/json" in ctype:
                    raise ValueError("الرابط لم يرجع فيديو.")

                declared = int(resp.headers.get("Content-Length", "0") or 0)
                if declared > MAX_SAVE_BYTES:
                    raise ValueError(f"الفيديو أكبر من الحد المسموح للحفظ ({MAX_SAVE_MB} MB).")

                written = 0
                with open(temp_path, "wb") as out:
                    for chunk in resp.iter_content(chunk_size=524288):
                        if chunk:
                            written += len(chunk)
                            if written > MAX_SAVE_BYTES:
                                raise ValueError(f"الفيديو أكبر من الحد المسموح للحفظ ({MAX_SAVE_MB} MB).")
                            out.write(chunk)
            if written > 0:
                break
        except Exception as exc:
            last_exc = exc
            written = 0
            if os.path.exists(temp_path):
                os.remove(temp_path)

    if written == 0:
        return jsonify({"error": str(last_exc or "تعذر تحميل الفيديو.")}), 400

    os.replace(temp_path, filepath)
    return jsonify({"local_url": f"/media/{filename}", "cached": False})


@app.route("/media/<path:filename>")
def media(filename: str):
    return send_from_directory(STORAGE_DIR, filename, conditional=True)


if __name__ == "__main__":
    # للتشغيل المحلي فقط؛ على Render يُشغَّل عبر gunicorn
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
