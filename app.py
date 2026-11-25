import concurrent.futures
from datetime import datetime
import json
import os
import random
import re
import sys
import threading
import time
from flask import Flask, jsonify, render_template_string, request
import requests

# ==========================================
# --- إعدادات وتكوين خادم Flask ---
# ==========================================
app = Flask(__name__)

# المتغيرات العامة للتحكم في البوت
bot_state = {
    'is_running': False,
    'cookies': '',
    'total_sent': 0,
    'total_failed': 0,
    'total_skipped': 0,
    'current_page': 1,
    'cycle_count': 1,
    'start_time': None,
    'logs': [],
}

state_lock = threading.Lock()
file_lock = threading.Lock()
sent_ids = set()

# إعدادات الأداء
MAX_WORKERS = 4
MIN_DELAY = 1.5
MAX_DELAY = 3.5
CYCLE_REST_TIME = 30

USER_AGENTS = [
    'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
]

SEARCH_URL = 'https://m.buzzarab.com/ar/search_results.php'
PROFILE_URL = 'https://m.buzzarab.com/ar/showprofile.php'
MAIL_URL = 'https://m.buzzarab.com/ar/mail_compose.php'

MESSAGES = {
    'DZ': (
        'سلام، شفت البروفايل تاعك وعجبني، حاب نتعرف عليك فإطار علاقة'
        ' جديّة. فانتظار ردك مع كل الاحترام.\r\n'
    ),
    'MA': (
        'سلام، شفت البروفايل ديالك وعجبني، باغي نتعرف عليك فإطار علاقة'
        ' جديّة. فانتظار الرد ديالك.\r\n'
    ),
    'TN': (
        'عسلامة، شفت البروفيل متاعك، نحب نتعرف عليك في إطار علاقة جديّة.'
        ' في انتظار إجابتك.\r\n'
    ),
    'EG': (
        'أهلاً بك، شفت البروفايل بتاعك وحابب نتعرف أكتر في إطار علاقة جادّة.'
        ' منتظر ردك بكل احترام.\r\n'
    ),
    'SA': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'AE': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'KW': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'QA': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'BH': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'OM': (
        'هلا والله، شفت بروفايلك وحاب نتعرف أكثر في إطار علاقة جادة. بانتظار'
        ' ردك مع كل الاحترام.\r\n'
    ),
    'SY': (
        'مرحبا، شفت البروفايل تبعك وحابب نتعرف أكتر بإطار علاقة جديّة. بانتظار'
        ' ردك مع كامل الاحترام.\r\n'
    ),
    'JO': (
        'مرحبا، شفت البروفايل تبعك وحابب نتعرف أكتر بإطار علاقة جديّة. بانتظار'
        ' ردك مع كامل الاحترام.\r\n'
    ),
    'LB': (
        'مرحبا، شفت البروفايل تبعك وحابب نتعرف أكتر بإطار علاقة جديّة. بانتظار'
        ' ردك مع كامل الاحترام.\r\n'
    ),
    'PS': (
        'مرحبا، شفت البروفايل تبعك وحابب نتعرف أكتر بإطار علاقة جديّة. بانتظار'
        ' ردك مع كامل الاحترام.\r\n'
    ),
    'IQ': (
        'هلو، شفت البروفايل مالتك وحاب نتعرف أكثر بإطار علاقة جادة. بانتظار'
        ' ردج مع كل الاحترام.\r\n'
    ),
    'LY': (
        'مرحبتين، شفت البروفايل متاعك ونبي نتعرف عليك في إطار علاقة جديّة. في'
        ' انتظار ردك.\r\n'
    ),
    'SD': (
        'سلامات، شفت البروفايل بتاعك وحابب نتعرف أكتر في إطار علاقة جادة.'
        ' منتظر ردك مع كل الاحترام.\r\n'
    ),
    'YE': (
        'أهلاً وسهلاً، شفت البروفايل حقك وحابب نتعرف في إطار علاقة جادة.'
        ' بانتظار ردك مع كل الاحترام.\r\n'
    ),
    'ar_default': (
        'مرحباً، أرسل لك بعدما رأيت حسابك، وأتمنى التواصل معك برغبة في'
        ' التعارف الجاد والعلاقة الجدية. بانتظار ردك مع كل الاحترام.\r\n'
    ),
    'fr': (
        "Bonjour, j'ai trouvé votre profil sur cette application. Je souhaite"
        ' faire votre connaissance pour une relation sérieuse et stable. Au'
        ' plaisir de vous lire.\r\n'
    ),
    'en': (
        'Hello, I found your profile on this app and I would like to get to'
        ' know you for a serious and stable relationship. Looking forward to'
        ' your response.\r\n'
    ),
}

ARAB_COUNTRIES = {
    'MA',
    'DZ',
    'TN',
    'EG',
    'SA',
    'SY',
    'JO',
    'IQ',
    'YE',
    'AE',
    'KW',
    'QA',
    'BH',
    'OM',
    'LB',
    'PS',
    'LY',
    'SD',
}
FRENCH_COUNTRIES = {'FR', 'BE', 'CH', 'CA'}


# ==========================================
# --- إدارة ملف الحسابات المرسلة (sent_ids.txt) ---
# ==========================================
def load_sent_ids():
  """تحميل كافة الـ IDs التي تمت مراسلتها سابقاً من ملف sent_ids.txt"""
  if os.path.exists('sent_ids.txt'):
    try:
      with open('sent_ids.txt', 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())
    except Exception as e:
      add_log(f'خطأ أثناء قراءة sent_ids.txt: {e}', 'error')
  return set()


def save_sent_id(user_id):
  """حفظ الـ ID الجديد في ملف sent_ids.txt بشكل فوري وآمن"""
  with file_lock:
    try:
      with open('sent_ids.txt', 'a', encoding='utf-8') as f:
        f.write(f'{user_id}\n')
    except Exception as e:
      add_log(f'خطأ أثناء حفظ الـ ID في الملف: {e}', 'error')


# ==========================================
# --- وظائف المساعدة واللوجستيات ---
# ==========================================
def add_log(msg, log_type='info'):
  timestamp = datetime.now().strftime('%H:%M:%S')
  with state_lock:
    bot_state['logs'].append(
        {'time': timestamp, 'msg': msg, 'type': log_type}
    )
    if len(bot_state['logs']) > 300:
      bot_state['logs'].pop(0)


def create_session():
  session = requests.Session()
  session.headers.update({
      'User-Agent': random.choice(USER_AGENTS),
      'Accept': 'application/json, text/javascript, */*; q=0.01',
      'x-requested-with': 'XMLHttpRequest',
      'Content-Type': 'application/x-www-form-urlencoded',
      'accept-language': 'ar-DZ,ar;q=0.9,en-US;q=0.8,en;q=0.7',
      'Cookie': bot_state['cookies'],
  })
  return session


def detect_country_fast(session, profile_id):
  try:
    headers = {'referer': f'{PROFILE_URL}?id={profile_id}'}
    res = session.get(
        PROFILE_URL, params={'id': profile_id}, headers=headers, timeout=10
    )
    if res.status_code == 429:
      return 'ar_default', 'مجهول (429)'

    match_flag = re.search(r'/flags/\d+/([A-Z]{2})\.png', res.text)
    if match_flag:
      code = match_flag.group(1)
      return code, code

    if re.search(r'[\u0600-\u06FF]', res.text):
      return 'ar_default', 'عربي'
  except Exception:
    pass
  return 'ar_default', 'افتراضي'


def select_message(country_code):
  if country_code in MESSAGES:
    return MESSAGES[country_code]
  elif country_code in FRENCH_COUNTRIES:
    return MESSAGES['fr']
  elif country_code in ARAB_COUNTRIES:
    return MESSAGES['ar_default']
  return MESSAGES['en']


def send_message(session, recipient_id, message_text):
  headers = {'referer': f'{MAIL_URL}?recipient={recipient_id}'}
  payload = {
      'reply_to_id': '',
      'validate_form': 'validate_form',
      'txtrecipient': recipient_id,
      'is_paste': '0',
      'txtmessage': message_text,
      'btnsend': '',
  }
  try:
    res = session.post(
        MAIL_URL,
        params={'recipient': recipient_id},
        data=payload,
        headers=headers,
        timeout=12,
    )
    return res.status_code == 200
  except Exception:
    return False


def process_user(user_id):
  if not bot_state['is_running']:
    return

  # فحص ما إذا كان الحساب مرسلاً له سابقاً إما في هذه الجلسة أو من ملف sent_ids.txt
  if user_id in sent_ids:
    with state_lock:
      bot_state['total_skipped'] += 1
    add_log(f'متخطي (مُرسل سابقاً في sent_ids.txt): {user_id}', 'warning')
    return

  session = create_session()
  country_code, country_label = detect_country_fast(session, user_id)
  msg_text = select_message(country_code)

  if send_message(session, user_id, msg_text):
    with state_lock:
      bot_state['total_sent'] += 1
      sent_ids.add(user_id)

    # حفظ الـ ID فوراً داخل الملف لضمان عدم تكراره مستقبلاً
    save_sent_id(user_id)

    add_log(f'تم الإرسال بنجاح إلى: {user_id} ({country_label})', 'success')
  else:
    with state_lock:
      bot_state['total_failed'] += 1
    add_log(f'فشل الإرسال إلى: {user_id}', 'error')

  time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def fetch_page(session, page_num):
  params = {
      'l': 'arabic',
      'subfolder': '1',
      'base_limit': '1',
      'pageID': str(page_num),
      'pageFrom': str(page_num),
  }
  try:
    res = session.get(SEARCH_URL, params=params, timeout=15)
    if res.status_code == 200:
      try:
        return res.json().get('page', '')
      except Exception:
        return res.text
    elif res.status_code in [403, 429]:
      add_log(f'حظر موقت ({res.status_code}) - انتظار 10 ثوانٍ...', 'warning')
      time.sleep(10)
  except Exception as e:
    add_log(f'خطأ أثناء جلب الصفحة {page_num}: {str(e)}', 'error')
  return None


# ==========================================
# --- حلقة البوت البرمجية (Background Worker) ---
# ==========================================
def bot_worker():
  global sent_ids
  add_log('جاري قراءة ملف sent_ids.txt وإعداد البيانات...', 'info')

  # قراءة الـ IDs السابقة
  sent_ids = load_sent_ids()
  add_log(
      f'تم تحميل {len(sent_ids)} حساب مسجل سابقاً في sent_ids.txt', 'success'
  )

  main_session = create_session()

  while bot_state['is_running']:
    current_page = 1
    empty_page_count = 0

    while bot_state['is_running']:
      with state_lock:
        bot_state['current_page'] = current_page

      add_log(f'جاري فحص الصفحة رقم {current_page}...', 'info')
      html_content = fetch_page(main_session, current_page)

      if not html_content:
        empty_page_count += 1
        if empty_page_count >= 3:
          add_log('وصلت لنهاية صفحات البحث المتاحة.', 'warning')
          break
        current_page += 1
        continue

      found_ids = re.findall(
          r'(?:showprofile\.php\?id=|user_id=|profile_id=|id=)(\d+)',
          html_content,
      )
      page_ids = []
      for uid in found_ids:
        if uid not in page_ids and len(uid) >= 5:
          page_ids.append(uid)

      if not page_ids:
        empty_page_count += 1
        if empty_page_count >= 2:
          add_log('لا توجد حسابات جديدة في هذه الصفحة.', 'warning')
          break
      else:
        empty_page_count = 0
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as executor:
          futures = [executor.submit(process_user, uid) for uid in page_ids]
          concurrent.futures.wait(futures)

      current_page += 1
      time.sleep(1)

    if not bot_state['is_running']:
      break

    with state_lock:
      bot_state['cycle_count'] += 1

    add_log(
        f'اكتملت الدورة #{bot_state["cycle_count"]-1}. استراحة لمدة'
        f' {CYCLE_REST_TIME} ثانية...',
        'info',
    )

    for _ in range(CYCLE_REST_TIME):
      if not bot_state['is_running']:
        break
      time.sleep(1)

  add_log('تم إيقاف عمل البوت بنجاح.', 'warning')


# ==========================================
# --- مسارات Flask واجهة الويب (Web Endpoints) ---
# ==========================================
@app.route('/')
def index():
  return render_template_string(HTML_TEMPLATE)


@app.route('/api/start', methods=['POST'])
def start_bot():
  data = request.json or {}
  cookies_input = data.get('cookies', '').strip()

  if not cookies_input:
    return jsonify(
        {'status': 'error', 'message': 'يرجى إدخال نص الكوكيز أولاً!'}
    ), 400

  if bot_state['is_running']:
    return jsonify(
        {'status': 'error', 'message': 'البوت قيد التشغيل بالفعل!'}
    ), 400

  bot_state['cookies'] = cookies_input
  bot_state['is_running'] = True
  bot_state['start_time'] = time.time()

  thread = threading.Thread(target=bot_worker, daemon=True)
  thread.start()

  return jsonify({'status': 'success', 'message': 'تم تشغيل البوت بنجاح!'})


@app.route('/api/stop', methods=['POST'])
def stop_bot():
  bot_state['is_running'] = False
  return jsonify(
      {'status': 'success', 'message': 'جاري إيقاف عمل البوت...'}
  )


@app.route('/api/status', methods=['GET'])
def get_status():
  elapsed = max(1, time.time() - (bot_state['start_time'] or time.time()))
  speed = round((bot_state['total_sent'] / elapsed) * 60, 1)

  return jsonify({
      'is_running': bot_state['is_running'],
      'total_sent': bot_state['total_sent'],
      'total_failed': bot_state['total_failed'],
      'total_skipped': bot_state['total_skipped'],
      'current_page': bot_state['current_page'],
      'cycle_count': bot_state['cycle_count'],
      'speed': speed,
      'logs': bot_state['logs'],
  })


# ==========================================
# --- واجهة HTML/CSS/JS (Neon Cyberpunk UI) ---
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BuzzArab Auto Bot - Neon Edition</title>
    <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&family=Fira+Code:wght@400;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #08090d;
            --card-bg: rgba(18, 22, 36, 0.75);
            --neon-cyan: #00f2fe;
            --neon-magenta: #ff007f;
            --neon-green: #00ff87;
            --neon-yellow: #ffdd00;
            --neon-red: #ff3366;
            --text-main: #e2e8f0;
            --border-glow: rgba(0, 242, 254, 0.25);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Tajawal', sans-serif;
        }

        body {
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            padding: 20px;
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(0, 242, 254, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(255, 0, 127, 0.08) 0%, transparent 40%);
            background-attachment: fixed;
        }

        .container {
            max-width: 1100px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        /* Header Styling */
        header {
            text-align: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border-glow);
            position: relative;
        }

        header h1 {
            font-size: 2.2rem;
            font-weight: 900;
            background: linear-gradient(90deg, var(--neon-cyan), var(--neon-magenta));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 20px rgba(0, 242, 254, 0.3);
            letter-spacing: 1px;
        }

        header p {
            color: #94a3b8;
            font-size: 0.95rem;
            margin-top: 5px;
        }

        /* Grid Layout */
        .dashboard-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }

        @media (max-width: 850px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
        }

        /* Glassmorphism Card */
        .card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-glow);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            transition: border-color 0.3s ease;
        }

        .card:hover {
            border-color: rgba(0, 242, 254, 0.5);
        }

        .card-title {
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--neon-cyan);
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }

        .stat-box {
            background: rgba(10, 12, 20, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 12px;
            text-align: center;
        }

        .stat-value {
            font-size: 1.6rem;
            font-weight: 900;
            margin-top: 4px;
        }

        .stat-label {
            font-size: 0.8rem;
            color: #94a3b8;
        }

        /* Colors for Stat Boxes */
        .val-sent { color: var(--neon-green); text-shadow: 0 0 10px rgba(0, 255, 135, 0.3); }
        .val-failed { color: var(--neon-red); text-shadow: 0 0 10px rgba(255, 51, 102, 0.3); }
        .val-skipped { color: var(--neon-yellow); }
        .val-page { color: var(--neon-cyan); }
        .val-cycle { color: var(--neon-magenta); }
        .val-speed { color: #a78bfa; }

        /* Inputs & Textarea */
        textarea {
            width: 100%;
            height: 140px;
            background: rgba(10, 12, 20, 0.8);
            border: 1px solid rgba(0, 242, 254, 0.2);
            border-radius: 10px;
            padding: 12px;
            color: #a5f3fc;
            font-family: 'Fira Code', monospace;
            font-size: 0.85rem;
            resize: vertical;
            outline: none;
            transition: all 0.3s ease;
        }

        textarea:focus {
            border-color: var(--neon-cyan);
            box-shadow: 0 0 12px rgba(0, 242, 254, 0.25);
        }

        /* Action Buttons */
        .btn-group {
            display: flex;
            gap: 12px;
            margin-top: 15px;
        }

        button {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 10px;
            font-weight: 700;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }

        .btn-start {
            background: linear-gradient(135deg, var(--neon-cyan), #0072ff);
            color: #000;
            box-shadow: 0 0 15px rgba(0, 242, 254, 0.3);
        }

        .btn-start:hover {
            transform: translateY(-2px);
            box-shadow: 0 0 25px rgba(0, 242, 254, 0.6);
        }

        .btn-stop {
            background: linear-gradient(135deg, #ff0844, #ffb199);
            color: #fff;
            box-shadow: 0 0 15px rgba(255, 8, 68, 0.3);
        }

        .btn-stop:hover {
            transform: translateY(-2px);
            box-shadow: 0 0 25px rgba(255, 8, 68, 0.6);
        }

        button:disabled {
            opacity: 0.4;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none !important;
        }

        /* Terminal Console Logs */
        .terminal {
            background: #050608;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            height: 380px;
            overflow-y: auto;
            padding: 15px;
            font-family: 'Fira Code', monospace;
            font-size: 0.85rem;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .log-line {
            line-height: 1.4;
            display: flex;
            gap: 10px;
            word-break: break-word;
        }

        .log-time {
            color: #64748b;
            user-select: none;
        }

        .log-info { color: #38bdf8; }
        .log-success { color: var(--neon-green); }
        .log-warning { color: var(--neon-yellow); }
        .log-error { color: var(--neon-red); }

        /* Status Badge */
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 700;
        }

        .status-running {
            background: rgba(0, 255, 135, 0.15);
            color: var(--neon-green);
            border: 1px solid var(--neon-green);
        }

        .status-stopped {
            background: rgba(255, 51, 102, 0.15);
            color: var(--neon-red);
            border: 1px solid var(--neon-red);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: currentColor;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.3; }
            100% { opacity: 1; }
        }
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>⚡ BUZZARAB AUTOMATION BOT</h1>
        <p>نظام إرسال الرسائل التلقائي المطور مع خاصية الحفظ الذكي في sent_ids.txt</p>
    </header>

    <div class="dashboard-grid">
        <!-- قسم التحكم وإدخال البيانات -->
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <div class="card-title" style="margin: 0;">🔑 بيانات الجلسة (Cookies)</div>
                <div id="statusBadge" class="status-badge status-stopped">
                    <span class="pulse-dot"></span>
                    <span id="statusText">متوقف</span>
                </div>
            </div>

            <textarea id="cookiesInput" placeholder="ضع نص الكوكيز الكامل هنا (buzzarabosdate_info=...)..."></textarea>

            <div class="btn-group">
                <button id="startBtn" class="btn-start" onclick="startBot()">
                    🚀 تشغيل (START)
                </button>
                <button id="stopBtn" class="btn-stop" onclick="stopBot()" disabled>
                    🛑 إيقاف (STOP)
                </button>
            </div>
        </div>

        <!-- قسم الإحصائيات -->
        <div class="card">
            <div class="card-title">📊 إحصائيات الأداء الحية</div>
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">الناجحة</div>
                    <div id="statSent" class="stat-value val-sent">0</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">الفاشلة</div>
                    <div id="statFailed" class="stat-value val-failed">0</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">المتخطاة</div>
                    <div id="statSkipped" class="stat-value val-skipped">0</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">الصفحة الحالية</div>
                    <div id="statPage" class="stat-value val-page">1</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">الدورة الحالية</div>
                    <div id="statCycle" class="stat-value val-cycle">1</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">السرعة (ر/د)</div>
                    <div id="statSpeed" class="stat-value val-speed">0.0</div>
                </div>
            </div>
        </div>
    </div>

    <!-- قسم الشاشات والسجلات -->
    <div class="card">
        <div class="card-title">🖥️ سجل المحاكاة المباشر (Terminal)</div>
        <div id="terminal" class="terminal">
            <div class="log-line log-info">
                <span class="log-time">[00:00:00]</span>
                <span>في انتظار إدخال الكوكيز والضغط على زر التشغيل...</span>
            </div>
        </div>
    </div>
</div>

<script>
    let isPolling = false;

    async function startBot() {
        const cookies = document.getElementById('cookiesInput').value.trim();
        if (!cookies) {
            alert('يرجى إدخال نص الكوكيز أولاً!');
            return;
        }

        try {
            const res = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookies: cookies })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                document.getElementById('startBtn').disabled = true;
                document.getElementById('stopBtn').disabled = false;
                document.getElementById('cookiesInput').disabled = true;
                if (!isPolling) startPolling();
            } else {
                alert(data.message);
            }
        } catch (e) {
            alert('حدث خطأ أثناء الاتصال بالخادم!');
        }
    }

    async function stopBot() {
        try {
            const res = await fetch('/api/stop', { method: 'POST' });
            const data = await res.json();
            document.getElementById('stopBtn').disabled = true;
        } catch (e) {
            console.error(e);
        }
    }

    function startPolling() {
        isPolling = true;
        const interval = setInterval(async () => {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                // تحديث الواجهة والعدادات
                document.getElementById('statSent').innerText = data.total_sent;
                document.getElementById('statFailed').innerText = data.total_failed;
                document.getElementById('statSkipped').innerText = data.total_skipped;
                document.getElementById('statPage').innerText = data.current_page;
                document.getElementById('statCycle').innerText = data.cycle_count;
                document.getElementById('statSpeed').innerText = data.speed;

                // تحديث حالة التشغيل
                const badge = document.getElementById('statusBadge');
                const text = document.getElementById('statusText');
                if (data.is_running) {
                    badge.className = 'status-badge status-running';
                    text.innerText = 'شغال الآن';
                    document.getElementById('startBtn').disabled = true;
                    document.getElementById('stopBtn').disabled = false;
                } else {
                    badge.className = 'status-badge status-stopped';
                    text.innerText = 'متوقف';
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('stopBtn').disabled = true;
                    document.getElementById('cookiesInput').disabled = false;
                }

                // تحديث سجل السطور Terminal
                const terminal = document.getElementById('terminal');
                terminal.innerHTML = '';
                data.logs.forEach(log => {
                    const line = document.createElement('div');
                    line.className = `log-line log-${log.type}`;
                    line.innerHTML = `<span class="log-time">[${log.time}]</span> <span>${log.msg}</span>`;
                    terminal.appendChild(line);
                });
                terminal.scrollTop = terminal.scrollHeight;

            } catch (e) {
                console.error(e);
            }
        }, 1000);
    }

    // بدء التحديث التلقائي عند فتح الصفحة
    startPolling();
</script>

</body>
</html>
"""

# ==========================================
# --- النقطة الرئيسية لتشغيل تطبيق الويب ---
# ==========================================
if __name__ == '__main__':
  print('\n' + '=' * 60)
  print('🚀 تم تشغيل خادم الويب بنجاح!')
  print('🌐 افتح المتصفح وادخل إلى الرابط التالي:')
  print('👉 http://127.0.0.1:5000')
  print('=' * 60 + '\n')

  app.run(host='0.0.0.0', port=5000, debug=False)
