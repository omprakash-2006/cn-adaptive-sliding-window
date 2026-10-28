"""College-style examination portal with hidden correction-safe delivery checks.

Student UI retains the college branding with subtle 3D depth. The optional local
lab is enabled only by launch.py --demo. All records are synthetic samples.
"""

import http.server
import socketserver
import urllib.parse
import json
import threading
import time
import uuid
import os
import concurrent.futures
import copy
import ipaddress
from html import escape
from student_roster import normalize_roll
from publication import EXAM_ID, VerificationUnavailable
from portal_safety import guard_result, resolve_result, unavailable_page
import correction_lab
from frontend_effects import enhance_portal, CONFETTI

import protocol
import server
import client

WEB_PORT = 8080
DEMO_ENABLED = False
TCP_SERVER_PORT = 65433
CREST_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mepco_crest.png")
CAMPUS_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mepco_campus.jpg")
ENTRANCE_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mepco_entrance.jpg")

# Global in-memory query sessions for real-time queue telemetry
QUERY_SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
CACHED_RESULTS = {}  # (exam_id, roll_number) -> (versioned result, monotonic timestamp)

# Global telemetry metrics
TOTAL_BURST_QUERIES = 0
SESSION_RETENTION_SECONDS = 300


def request_student_result(roll_number, timeout=8, queue_callback=None):
    """Observe the real portal TCP request without changing admission or delivery."""
    request_id = uuid.uuid4().hex
    evidence = server.REQUEST_EVIDENCE
    evidence.start_portal(request_id, roll_number)

    def telemetry(position, total, status):
        evidence.portal_queue(request_id, position)
        if queue_callback:
            queue_callback(position, total, status)

    try:
        result = client.request_result(roll_number, host='127.0.0.1', port=TCP_SERVER_PORT,
                                       timeout=timeout, verbose=False,
                                       queue_callback=telemetry, request_id=request_id)
    except Exception:
        evidence.finish_portal(request_id, {})
        raise
    evidence.finish_portal(request_id, result)
    return result


def cleanup_completed_sessions():
    """Expire finished sessions without removing students still in FIFO."""
    now = time.monotonic()
    with SESSIONS_LOCK:
        expired = [key for key, session in QUERY_SESSIONS.items()
                   if session.get("done") and now - session.get("completed_at", now) > SESSION_RETENTION_SECONDS]
        for key in expired:
            del QUERY_SESSIONS[key]

# ============================================================================
# PAGE 1: SEARCH PORTAL WITH LIVE QUEUE WAITING SCREEN & LAB CONTROLS
# ============================================================================
HTML_PORTAL_PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>End Semester Examinations Results MAY 2026</title><style>
@font-face{font-family:Poppins;src:url('/poppins-400.ttf') format('truetype');font-weight:400;font-display:swap}@font-face{font-family:Poppins;src:url('/poppins-500.ttf') format('truetype');font-weight:500;font-display:swap}@font-face{font-family:Poppins;src:url('/poppins-700.ttf') format('truetype');font-weight:700;font-display:swap}
*,:before,:after{box-sizing:border-box}body{margin:0;font-family:Poppins,sans-serif;font-size:16px;font-weight:400;line-height:1.5;color:#212529;background:url('/college-background.jpg') center center/cover no-repeat fixed;min-height:100vh}button,input,a{font-family:inherit}button,a{touch-action:manipulation}a{text-decoration:none;color:#007bff}a:hover{color:#0056b3}button{cursor:pointer}button:disabled{opacity:.6;cursor:wait}a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #ffc107;outline-offset:3px}
.login-area{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:100%;max-width:700px}.portal-card{display:flex;margin:0 -15px;background:white}.left-panel{width:41.666667%;padding:0 15px;background:#007bff;color:white}.left-pannel{margin:80px 0}.crest-wrap{text-align:center}.crest-img{vertical-align:middle;width:250px;height:200px;object-fit:contain;max-width:100%}.college-name-left{font-size:14px;line-height:21px;margin:0 0 16px;white-space:nowrap}.circular-space{height:72px}.btn-circular{display:inline-flex;align-items:center;gap:5px;color:white;background:#da573b;border:1px solid #be5238;padding:6px 12px;border-radius:4px;font-size:16px;line-height:24px;font-weight:400}.btn-circular:hover{background:#be5238;border-color:#9b4631;color:white}.btn-circular svg{width:15px;height:15px}
.right-panel{width:58.333333%;padding:0 15px;background:white}.right-side{margin:40px 0}.main-heading{font-size:28px;font-weight:500;line-height:1.2;color:blue;text-align:center;margin:0 0 8px}.main-heading hr{margin:16px 0;border:0;border-top:1px solid rgba(0,0,0,.1)}.sub-heading{font-size:24px;font-weight:500;line-height:1.2;color:#ff6600;text-align:center;margin:16px 0 8px}.dotted-line{font-weight:700;color:#841fec;line-height:24px;white-space:nowrap;overflow:hidden}.course-links{text-align:center;font-weight:700;font-size:16px;line-height:24px;margin:0 0 16px;color:#007bff}.course-links .arrear{color:orange}.login-box{font-weight:500;margin-top:24px;padding-top:24px}.form-group{margin-bottom:16px}.mepco-input{display:block;width:100%;height:50px;min-height:50px;padding:20px;border:1px solid #ced4da;border-radius:4px;background:white;color:#495057;font-size:16px;line-height:24px;font-weight:400;transition:border-color .15s,box-shadow .15s}.mepco-input::placeholder{color:#6c757d;opacity:1}.mepco-input:focus{border-color:#80bdff;outline:0;box-shadow:0 0 0 3px #007bff40}.btn-results{display:block;width:100%;margin-top:48px;padding:8px 16px;background:#007bff;border:1px solid #007bff;border-radius:4px;color:white;font-size:20px;font-weight:400;line-height:30px}.btn-results:hover{background:#0069d9;border-color:#0062cc}
.lab-control-bar{position:fixed;bottom:14px;right:14px;z-index:80;font-size:12px;max-width:calc(100vw - 28px);color:#334155;border:1px solid #cbd5e1;border-radius:6px;background:#fff;box-shadow:0 3px 15px #0002}.lab-control-bar summary{cursor:pointer;padding:8px 12px;font-size:11px;list-style:none;display:flex;align-items:center;gap:7px}.lab-control-bar summary::-webkit-details-marker{display:none}.lab-control-bar summary:after{content:'+';margin-left:auto}.lab-control-bar[open] summary:after{content:'−'}.lab-control-bar[open]{width:440px}.lab-actions{display:flex;gap:8px;flex-wrap:wrap;padding:14px;border-top:1px solid #e2e8f0}.btn-lab{border:1px solid #bfdbfe;background:#eff6ff;color:#0056b3;border-radius:4px;padding:8px 10px;font-size:11px;font-weight:500}.btn-lab:hover{background:#dbeafe}.telemetry-pill{width:100%;font-size:11px;color:#1d4ed8;padding:10px 0 0}.demo-note{padding:0 14px 14px;margin:0;color:#64748b;font-size:10px}.demo-note a{font-weight:500}.skip-link{position:fixed;top:-100px;z-index:300;left:10px;padding:10px;background:#fff}.skip-link:focus{top:10px}
.queue-modal-overlay{position:fixed;inset:0;z-index:200;display:none;justify-content:center;align-items:center;padding:16px;background:#09192fac;backdrop-filter:blur(4px)}.queue-modal-card{width:460px;max-width:100%;background:white;border-radius:8px;padding:30px;text-align:center;box-shadow:0 16px 45px #0004;border-top:5px solid #007bff;max-height:90svh;overflow:auto;outline:none}.queue-crest{width:64px;height:64px;object-fit:contain}.queue-modal-card h3{font-size:20px;font-weight:500;color:blue;margin:14px 0 8px;line-height:1.4}.queue-intro{color:#64748b;font-size:12px;line-height:1.8;margin:0 0 22px}.queue-stats-box{display:flex;gap:12px;margin-bottom:22px}.queue-stat-item{width:50%;border:1px solid #e2e8f0;padding:14px 10px;background:#f8fafc;border-radius:4px}.stat-lbl{font-size:10px;color:#64748b;margin-bottom:6px}.stat-val{font-size:23px;color:#007bff!important;font-weight:500}.progress-track{height:7px;border-radius:5px;overflow:hidden;background:#e2e8f0}.progress-bar-fill{height:100%;background:#007bff;transition:width .25s}.progress-description{display:flex;justify-content:space-between;gap:12px;margin-top:10px;font-size:10px;color:#64748b;text-align:left}[hidden]{display:none!important}.queue-protocol-badge{background:#eff6ff;border:1px solid #bfdbfe;border-radius:4px;padding:11px;margin-top:22px;font-size:11px;color:#1d4ed8}
@media(max-height:710px) and (min-width:768px){.login-area{position:relative;transform:none;left:auto;top:auto;margin:24px auto}.portal-card{margin:0 -15px}}
@media(max-width:767px){body{background-position:top center}.login-area{position:relative;top:auto;left:auto;transform:none;max-width:450px;width:calc(100% - 32px);margin:24px auto 16px}.portal-card{flex-direction:column;margin:0}.left-panel,.right-panel{width:100%;padding:0 20px}.left-pannel{margin:24px 0;display:flex;flex-direction:column;align-items:center}.crest-img{width:180px;height:130px}.college-name-left{white-space:normal;text-align:center;font-size:12px;margin-bottom:14px}.circular-space{display:none}.btn-circular{font-size:12px;padding:5px 10px}.right-side{margin:28px 0}.main-heading{font-size:24px}.sub-heading{font-size:21px}.course-links{font-size:13px;line-height:22px}.login-box{padding-top:15px;margin-top:15px}.btn-results{margin-top:30px}.dotted-line{font-size:13px;text-align:center}.queue-modal-card{padding:25px 20px}.stat-val{font-size:20px}.lab-control-bar{position:relative;bottom:auto;right:auto;width:calc(100% - 32px);max-width:450px;margin:16px auto 20px}.queue-modal-card h3{font-size:19px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}.crest-img{display:none}.crest-still{display:block!important;width:130px;height:130px;object-fit:contain;margin:0 auto 10px}}
</style></head><body><a class="skip-link" href="#regNoInput">Skip to result search</a>
<main class="login-area"><div class="portal-card"><section class="left-panel"><div class="left-pannel"><div class="crest-wrap"><img src="/college-logo.gif" class="crest-img" alt="Mepco Schlenk crest"><img src="/mepco_crest.png" class="crest-still" alt="Mepco Schlenk crest" style="display:none"></div><p class="college-name-left">Mepco Schlenk Engg. College, Sivakasi</p><div class="circular-space"></div><a href="https://www.mepcoeng.ac.in/result/result57/r2023/resultcircular.pdf" class="btn-circular" target="_blank" rel="noopener noreferrer"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 4H4v16h16v-8M15 3l6 6-10 10H5v-6zM13 5l6 6"/></svg>Photocopy Circular</a></div></section>
<section class="right-panel"><div class="right-side"><h3 class="main-heading">Mepco Schlenk Engg.<br>College(Autonomous),<br>Sivakasi<hr></h3><h4 class="sub-heading">End Semester Examinations<br>Results - MAY 2026</h4><div class="dotted-line" aria-hidden="true">-----------------------------------------</div><p class="course-links">IV and VI Semester B.E. / B.Tech. / B.Arch., Regular Results<br><span class="arrear">R2023 (PG) / R2019 (UG) - Arrear Results</span><br>IV Semester M.E. / MCA / Ph.D Regular Results<br><br></p>
<div id="searchView"><form class="login-box" onsubmit="handleQuerySubmit(event)"><div class="form-group"><input name="roll" id="regNoInput" class="mepco-input" type="text" placeholder="24BAD001" aria-label="Register Number" pattern="24BAD(00[1-9]|0[1-9][0-9]|1[0-2][0-9]|130)" title="Use 24BAD001 to 24BAD130" oninput="this.value=this.value.replace(/\s/g,'').toUpperCase()" autocomplete="off" spellcheck="false" required></div><div class="form-group"><input name="dob" id="dobInput" class="mepco-input" type="text" placeholder="dd-mm-yyyy" aria-label="Date of birth" title="Enter valid DD-MM-YYYY data" pattern="(0[1-9]|1[0-9]|2[0-9]|3[01])-(0[1-9]|1[012])-[0-9]{4}" inputmode="numeric" required></div><button id="btnSubmit" class="btn-results" type="submit">Results</button></form></div></div></section></div></main>

<div id="queueModal" class="queue-modal-overlay"><section class="queue-modal-card" role="dialog" aria-modal="true" aria-labelledby="queueTitle" aria-describedby="queueIntro" tabindex="-1"><img src="/mepco_crest.png" class="queue-crest" alt=""><h3 id="queueTitle">Your Result Request Is Active</h3><p id="queueIntro" class="queue-intro">The examination server is managing incoming requests.<br>Keep this page open. Your result will appear automatically.</p><div class="queue-stats-box" aria-live="polite" aria-atomic="true"><div class="queue-stat-item"><div class="stat-lbl">Live Queue Position</div><div id="queuePosVal" class="stat-val">Checking…</div></div><div class="queue-stat-item"><div class="stat-lbl">Estimated Wait Time</div><div id="queueEstVal" class="stat-val">Calculating…</div></div></div><div class="progress-track"><div id="progressBarFill" class="progress-bar-fill" style="width:20%"></div></div><div class="progress-description"><span id="queueStatusText">Connecting to the server…</span><span id="queuePercentText">Please wait</span></div><div class="queue-protocol-badge">Your place is saved · No need to refresh this page</div><a id="queueRetry" href="/" hidden style="display:inline-block;margin-top:16px;color:#007bff">Return to result search</a></section></div>
  <script>
    async function queueRequest(url, timeoutMs) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {cache: 'no-store', signal: controller.signal});
        if (!response.ok) throw new Error('Server unavailable');
        return await response.json();
      } finally { clearTimeout(timer); }
    }

    function queueError(message) {
      document.getElementById('queueStatusText').innerText = message;
      document.getElementById('queuePosVal').innerText = 'Unavailable';
      document.getElementById('queueEstVal').innerText = '—';
      document.getElementById('queuePercentText').innerText = 'Please retry';
      document.getElementById('queueRetry').hidden = false;
      document.querySelector('.queue-protocol-badge').hidden = true;
      document.getElementById('progressBarFill').style.width = '0%';
    }

    async function handleQuerySubmit(e) {
      e.preventDefault();
      const btn = document.getElementById('btnSubmit');
      if (btn.disabled) return;
      const roll = document.getElementById('regNoInput').value.replace(/\s/g,'').toUpperCase();
      btn.disabled = true;
      btn.innerText = 'Connecting…';
      const modal = document.getElementById('queueModal');
      modal.style.display = 'flex';
      modal.querySelector('.queue-modal-card').focus();
      document.getElementById('queueRetry').hidden = true;
      document.getElementById('queuePosVal').innerText = 'Checking…';
      document.getElementById('queueStatusText').innerText = 'Connecting. A sleeping server may take a moment to start…';
      try {
        const data = await queueRequest('/api/query_start?roll=' + encodeURIComponent(roll), 115000);
        if (!data || typeof data.session_id !== 'string' || !data.session_id) throw new Error('Invalid session');
        await pollQueueProgress(data.session_id, roll);
      } catch {
        queueError('Could not start your request. Please return to result search and try again.');
      }
    }

    async function pollQueueProgress(sessionId, roll) {
      const posVal = document.getElementById('queuePosVal');
      const estVal = document.getElementById('queueEstVal');
      const barFill = document.getElementById('progressBarFill');
      const statusText = document.getElementById('queueStatusText');
      const pctText = document.getElementById('queuePercentText');
      let initialPosition = 0, failures = 0;
      // Schedule the next poll only after this one finishes: one request per student at a time.
      async function poll() {
        let nextDelay = 500;
        try {
          const data = await queueRequest('/api/query_poll?session_id=' + encodeURIComponent(sessionId), 15000);
          if (!data || typeof data.done !== 'boolean' || (!data.done && !Number.isFinite(data.position))) {
            throw new Error('Invalid queue update');
          }
          failures = 0;
          if (data.done) {
            if (!data.result || !data.result.success) {
              queueError(data.result && data.result.status_message === 'RECORD_NOT_FOUND'
                ? 'Register number not found. Please check your details.'
                : 'Your result is temporarily unavailable. Please return to result search.');
              return;
            }
            statusText.innerText = 'Your result is ready. Opening marksheet…';
            posVal.innerText = 'Completed!';
            estVal.innerText = '0.0s';
            barFill.style.width = '100%';
            pctText.innerText = 'Ready';
            window.location.href = '/result?roll=' + encodeURIComponent(roll);
            return;
          }
          if (data.position > 0) {
            initialPosition = Math.max(initialPosition, data.position);
            posVal.innerText = `#${data.position} of ${data.total_queued || data.position}`;
            const estimate = Number(data.estimated_sec);
            estVal.innerText = Number.isFinite(estimate) ? `~${estimate.toFixed(1)}s` : 'Calculating…';
            barFill.style.width = Math.min(90, 20 + 70 * (1 - data.position / initialPosition)) + '%';
            pctText.innerText = 'Waiting';
            statusText.innerText = 'Your place is saved. Please keep this page open.';
          } else {
            posVal.innerText = 'Processing';
            estVal.innerText = 'Please wait';
            barFill.style.width = '95%';
            pctText.innerText = 'Preparing result';
            statusText.innerText = 'Preparing your marksheet…';
          }
        } catch {
          failures += 1;
          if (failures >= 3) {
            queueError('Connection interrupted. Please return to result search and try again.');
            return;
          }
          statusText.innerText = 'Reconnecting to your existing request…';
          nextDelay = failures * 1000;
        }
        setTimeout(poll, nextDelay);
      }
      await poll();
    }
  </script></body></html>"""


HTML_PORTAL_PAGE = enhance_portal(HTML_PORTAL_PAGE)

# ============================================================================
# PAGE 2: SEPARATE RESULTS CERTIFICATE PAGE (/result?roll=...)
# ============================================================================
COLLEGE_DETAIL_STYLE = """
@font-face{font-family:Poppins;src:url('/poppins-400.ttf') format('truetype');font-weight:400;font-display:swap}@font-face{font-family:Poppins;src:url('/poppins-500.ttf') format('truetype');font-weight:500;font-display:swap}@font-face{font-family:Poppins;src:url('/poppins-700.ttf') format('truetype');font-weight:700;font-display:swap}
body{font-family:Poppins,sans-serif}.certificate-sheet{animation:none}.marks-table th:nth-child(1){width:5%!important}.marks-table th:nth-child(2){width:13%!important}.marks-table th:nth-child(4){width:7%!important}.marks-table th:nth-child(5){width:9%!important}.marks-table th:nth-child(6){width:7%!important}.marks-table th:nth-child(7){width:10%!important}.marks-table th:nth-child(8){width:11%!important}.cert-title-group h1{color:blue}.marks-table th,.students-table th,.btn-print{background:#007bff;border-color:#007bff}.certificate-sheet{border-top-color:#007bff}.cert-header{border-bottom-color:#007bff}.exam-tag{color:#ff6600}.summary-val-gpa{color:blue}.table-scroll{width:100%;overflow-x:auto}.marks-table{min-width:600px}.students-table{min-width:700px}.err-card p{overflow-wrap:anywhere}.crest-box img{animation:none}
@media(max-width:700px){body{padding:22px 12px}.certificate-sheet{padding:26px 18px}.cert-header{flex-direction:column;gap:12px}.cert-title-group h1{font-size:18px}.exam-tag{font-size:10px;line-height:1.7}.bio-grid td{font-size:10px;padding:9px 7px}.bio-value{overflow-wrap:anywhere}.bio-value[style]{font-size:11px!important}.summary-card{padding:15px 12px;gap:10px}.summary-label{font-size:9px}.summary-val-pass{font-size:14px}.sign-section{gap:15px}.seal-block{font-size:9px;max-width:55%}.dir-header{flex-direction:column;align-items:flex-start;gap:16px}.dir-title h1{font-size:16px}.dir-actions{flex-wrap:wrap;gap:10px}.controls-strip{flex-direction:column;align-items:stretch;gap:12px}.search-input{min-width:0!important;width:100%}.stats-pill{white-space:normal}.action-bar{gap:10px;flex-wrap:wrap}.btn-top{font-size:11px;padding:9px 12px}.telemetry-ribbon{flex-wrap:wrap;gap:8px}}
@media print{.table-scroll{overflow:visible}.marks-table{min-width:0}.cert-header{flex-direction:row}.certificate-sheet{padding:24px;animation:none}.summary-card,.sign-section,tr{break-inside:avoid}.action-bar,.telemetry-ribbon{display:none!important}.crest-box img{animation:none}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
"""

def generate_result_page(roll_number: str, res_info: dict) -> str:
    """Generates the dedicated full-page official result certificate."""
    res_info = guard_result(roll_number, res_info, server.PUBLICATIONS)
    if not res_info.get("success") and res_info.get("status_message") != "RECORD_NOT_FOUND":
        return unavailable_page()
    success = res_info.get("success", False)
    data = res_info.get("result_data") or {}
    scores = data.get("scores", {})
    # This renderer never reads the unversioned legacy student dictionary.
    roll_number = escape(roll_number)
    if not success or not data or data.get("status") == "RECORD_NOT_FOUND" or not scores:
        # Student not found page
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Result Not Found - Mepco Schlenk Engineering College</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #09192f url('/mepco_entrance.jpg') no-repeat center center fixed;
      background-size: cover;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
      color: #333;
    }}
    .err-card {{
      background: #fff;
      padding: 40px;
      border-radius: 6px;
      text-align: center;
      max-width: 500px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.4);
    }}
    h2 {{ color: #dc2626; margin-bottom: 12px; }}
    p {{ color: #475569; font-size: 14px; margin-bottom: 24px; }}
    .btn-back {{
      display: inline-block;
      background: #0077ff;
      color: #fff;
      padding: 10px 24px;
      border-radius: 4px;
      text-decoration: none;
      font-weight: 700;
      font-size: 14px;
    }}
    {COLLEGE_DETAIL_STYLE}
  </style>
</head>
<body>
  <div class="err-card">
    <h2>Record Not Found</h2>
    <p>Register Number <strong>{roll_number}</strong> was not found in the May 2026 Examination database. Please verify your registration number and try again.</p>
    <a href="/" class="btn-back">← Back to Results Search</a>
  </div>
</body>
</html>"""

    # Student found - render full official marksheet
    name = (data.get("name", "N/A")).upper()
    branch = data.get("branch", "Computer Science")
    semester = data.get("semester", "6th Semester")
    gpa = data.get("gpa", 0.0)
    status = data.get("status", "PASS")

    sub_codes = {
        "Computer Networks": "19CS601",
        "Operating Systems": "19CS602",
        "Database Systems": "19CS603",
        "Software Engineering": "19CS604"
    }

    credits_map = {
        "Computer Networks": 4,
        "Operating Systems": 4,
        "Database Systems": 3,
        "Software Engineering": 3
    }

    table_rows = ""
    sno = 1
    total_credits = 0
    earned_credits = 0

    for subj, mark in scores.items():
        code = sub_codes.get(subj, "19CS60X")
        c = credits_map.get(subj, 3)
        total_credits += c
        is_pass = mark >= 40
        if is_pass:
            earned_credits += c
            grade = 'O' if mark >= 85 else 'A+' if mark >= 75 else 'A' if mark >= 65 else 'B+' if mark >= 55 else 'B'
            pts = 10 if mark >= 85 else 9 if mark >= 75 else 8 if mark >= 65 else 7 if mark >= 55 else 6
            res_txt = "PASS"
            badge = '<span class="badge-pass">PASS</span>'
        else:
            grade = 'U'
            pts = 0
            res_txt = "RA"
            badge = '<span class="badge-fail">RE-APPEAR (RA)</span>'

        table_rows += f"""
        <tr>
          <td style="text-align: center;">{sno}</td>
          <td style="text-align: center; font-weight: 700; color: #0022cc;">{code}</td>
          <td><strong>{subj}</strong></td>
          <td style="text-align: center;">{c}</td>
          <td style="text-align: center;">{mark}</td>
          <td style="text-align: center; font-weight: 800;">{grade}</td>
          <td style="text-align: center;">{pts}</td>
          <td style="text-align: center;">{badge}</td>
        </tr>
        """
        sno += 1

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Result - {roll_number} - Mepco Schlenk Engineering College</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: #09192f url('/mepco_entrance.jpg') no-repeat center center fixed;
      background-size: cover;
      color: #1e293b;
      min-height: 100vh;
      padding: 30px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }}

    /* Top Action Bar */
    .action-bar {{
      width: 100%;
      max-width: 880px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }}
    .btn-top {{
      background: rgba(255, 255, 255, 0.15);
      backdrop-filter: blur(8px);
      color: #ffffff;
      border: 1px solid rgba(255, 255, 255, 0.3);
      padding: 8px 18px;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }}
    .btn-top:hover {{
      background: rgba(255, 255, 255, 0.28);
      transform: translateY(-1px);
    }}
    .btn-print {{
      background: #0077ff;
      border-color: #0077ff;
    }}
    .btn-print:hover {{
      background: #0066dd;
    }}

    /* Official Certificate Card */
    .certificate-sheet {{
      width: 100%;
      max-width: 880px;
      background: #ffffff;
      border-radius: 4px;
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.4);
      padding: 40px 48px;
      animation: fadeIn 0.25s ease-out;
      border-top: 6px solid #0022cc;
      position: relative;
    }}
    @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}

    /* Header Section */
    .cert-header {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 20px;
      border-bottom: 2px solid #0022cc;
      padding-bottom: 20px;
      margin-bottom: 24px;
      text-align: center;
    }}
    
    @keyframes globeRotation {{
      0% {{ transform: perspective(600px) rotateY(0deg); }}
      100% {{ transform: perspective(600px) rotateY(360deg); }}
    }}
    .crest-box {{
      width: 90px;
      height: 90px;
      perspective: 700px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .crest-box img {{
      width: 88px;
      height: 88px;
      border-radius: 50%;
      box-shadow: 0 4px 12px rgba(0,0,0,0.25);
      animation: globeRotation 7s linear infinite;
      transform-style: preserve-3d;
    }}

    .cert-title-group h1 {{
      font-size: 21px;
      font-weight: 800;
      color: #0022cc;
      letter-spacing: 0.2px;
      line-height: 1.25;
    }}
    .cert-title-group h2 {{
      font-size: 13px;
      font-weight: 600;
      color: #475569;
      margin-top: 3px;
    }}
    .cert-title-group h3 {{
      font-size: 12px;
      font-weight: 600;
      color: #64748b;
      margin-top: 2px;
    }}
    .exam-tag {{
      display: inline-block;
      margin-top: 8px;
      background: #fff7ed;
      border: 1px solid #ffedd5;
      color: #c2410c;
      font-size: 13.5px;
      font-weight: 800;
      padding: 4px 14px;
      border-radius: 20px;
      letter-spacing: 0.3px;
    }}

    /* Student Bio Table */
    .bio-grid {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-bottom: 24px;
      background: #f8fafc;
      border: 1px solid #cbd5e1;
    }}
    .bio-grid td {{
      padding: 8px 14px;
      border: 1px solid #e2e8f0;
    }}
    .bio-label {{
      color: #64748b;
      font-weight: 600;
      width: 22%;
      font-size: 12px;
    }}
    .bio-value {{
      color: #0f172a;
      font-weight: 700;
      width: 28%;
    }}

    /* Marks Table */
    .marks-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-bottom: 24px;
    }}
    .marks-table th {{
      background: #0022cc;
      color: #ffffff;
      padding: 10px 8px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid #0022cc;
      text-align: center;
    }}
    .marks-table td {{
      padding: 10px 12px;
      border: 1px solid #cbd5e1;
    }}
    .badge-pass {{
      display: inline-block;
      padding: 2px 8px;
      background: #dcfce7;
      color: #15803d;
      font-weight: 800;
      border-radius: 3px;
      font-size: 11px;
    }}
    .badge-fail {{
      display: inline-block;
      padding: 2px 8px;
      background: #fee2e2;
      color: #b91c1c;
      font-weight: 800;
      border-radius: 3px;
      font-size: 11px;
    }}

    /* Summary Strip */
    .summary-card {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: #f8fafc;
      border: 2px solid #cbd5e1;
      border-radius: 4px;
      padding: 14px 20px;
      margin-bottom: 24px;
    }}
    .summary-item {{
      text-align: center;
    }}
    .summary-label {{
      font-size: 11.5px;
      color: #64748b;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 2px;
    }}
    .summary-val-gpa {{
      font-size: 24px;
      font-weight: 800;
      color: #0022cc;
    }}
    .summary-val-pass {{
      font-size: 18px;
      font-weight: 800;
      color: #15803d;
    }}

    /* Seal & Verification */
    .sign-section {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      margin-top: 36px;
      padding-top: 20px;
      border-top: 1px dashed #cbd5e1;
    }}
    .seal-block {{
      text-align: center;
      color: #64748b;
      font-size: 11.5px;
      font-weight: 600;
    }}
    .seal-mark {{
      width: 70px;
      height: 70px;
      border: 2px dashed #94a3b8;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 6px auto;
      font-size: 10px;
      color: #94a3b8;
      font-weight: 700;
      text-transform: uppercase;
    }}

    /* CN Protocol Telemetry Ribbon */
    .telemetry-ribbon {{
      margin-top: 30px;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 4px;
      padding: 10px 14px;
      font-size: 11.5px;
      color: #1d4ed8;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    @media print {{
      body {{ background: #fff !important; padding: 0; }}
      .action-bar, .telemetry-ribbon {{ display: none !important; }}
      .certificate-sheet {{ box-shadow: none; border: 1px solid #000; width: 100%; max-width: 100%; }}
    }}
    {COLLEGE_DETAIL_STYLE}
  </style>
</head>
<body>

  <!-- Top Action Bar -->
  <div class="action-bar">
    <a href="/" class="btn-top">← Search Another Student</a>
    <button onclick="window.print()" class="btn-top btn-print">🖨️ Print / Save as PDF</button>
  </div>

  <!-- Official Marksheet Certificate Sheet -->
  <div class="certificate-sheet">

    <!-- Header -->
    <div class="cert-header">
      <div class="crest-box">
        <img src="/mepco_crest.png" alt="Mepco Schlenk Crest">
      </div>
      <div class="cert-title-group">
        <h1>MEPCO SCHLENK ENGINEERING COLLEGE</h1>
        <h2>(An Autonomous Institution, Affiliated to Anna University, Chennai)</h2>
        <h3>Sivakasi, Tamil Nadu – 626 005</h3>
        <div class="exam-tag">OFFICE OF THE CONTROLLER OF EXAMINATIONS — RESULTS MAY 2026</div>
      </div>
    </div>

    <!-- Student Bio Table -->
    <table class="bio-grid">
      <tr>
        <td class="bio-label">Register Number:</td>
        <td class="bio-value" style="color: #0022cc; font-size: 14px;">{roll_number}</td>
        <td class="bio-label">Regulation:</td>
        <td class="bio-value">2023 (Autonomous)</td>
      </tr>
      <tr>
        <td class="bio-label">Student Name:</td>
        <td class="bio-value">{name}</td>
        <td class="bio-label">Semester:</td>
        <td class="bio-value">{semester} (Regular)</td>
      </tr>
      <tr>
        <td class="bio-label">Degree & Branch:</td>
        <td class="bio-value" colspan="3">B.Tech - {branch}</td>
      </tr>
    </table>

    <!-- Grades Table -->
    <div class="table-scroll" role="region" aria-label="Subject grades" tabindex="0"><table class="marks-table">
      <thead>
        <tr>
          <th style="width: 8%;">S.No</th>
          <th style="width: 16%;">Course Code</th>
          <th style="text-align: left;">Course Title</th>
          <th style="width: 10%;">Credits</th>
          <th style="width: 10%;">Marks / 100</th>
          <th style="width: 10%;">Grade</th>
          <th style="width: 12%;">Grade Point</th>
          <th style="width: 16%;">Result</th>
        </tr>
      </thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>

    </div>
    <!-- Summary Card -->
    <div class="summary-card">
      <div class="summary-item">
        <div class="summary-label">Credits Earned</div>
        <div style="font-size: 20px; font-weight: 800; color: #0f172a;">{earned_credits} / {total_credits}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">Semester GPA (SGPA)</div>
        <div class="summary-val-gpa">{gpa}</div>
      </div>
      <div class="summary-item">
        <div class="summary-label">Final Classification</div>
        <div class="summary-val-pass" style="color: {'#15803d' if status == 'PASS' else '#b91c1c'}">{status}</div>
      </div>
    </div>

    <!-- Seal and Controller Signature -->
    <div class="sign-section">
      <div class="seal-block">
        <div class="seal-mark">OFFICIAL<br>SEAL</div>
        <div>Mepco Schlenk Autonomous</div>
      </div>
      <div class="seal-block">
        <div style="font-weight: 700; color: #0f172a; margin-bottom: 2px;">Dr. S. Arivazhagan, M.E., Ph.D.</div>
        <div>Controller of Examinations</div>
      </div>
    </div>

  </div>

{CONFETTI if status == 'PASS' else ''}
</body>
</html>"""


# ============================================================================
# PAGE 3: ALL STUDENTS DIRECTORY & BATCH TESTER PAGE (/students)
# ============================================================================
def generate_students_directory_page() -> str:
    rows = ""
    for i in range(1, 131):
        roll = f"24BAD{i:03d}"
        try:
            s = server.PUBLICATIONS.snapshot(roll) or {}
        except VerificationUnavailable:
            return unavailable_page()
        name = s.get("name", "N/A")
        branch = s.get("branch", "N/A")
        gpa = s.get("gpa", 0.0)
        status = s.get("status", "PASS")
        badge = '<span class="badge-pass">PASS</span>' if status == 'PASS' else '<span class="badge-fail">RA</span>'

        rows += f"""
        <tr class="student-row" data-search="{roll.lower()} {name.lower()} {branch.lower()}">
          <td style="text-align: center; font-weight: 700; color: #0022cc;">{roll}</td>
          <td><strong>{name}</strong></td>
          <td>{branch}</td>
          <td style="text-align: center; font-weight: 800;">{gpa}</td>
          <td style="text-align: center;">{badge}</td>
          <td style="text-align: center;">
            <a href="/result?roll={roll}" class="btn-view-res">📄 View Result</a>
          </td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>All Students Directory - Mepco Schlenk Engineering College</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: #09192f url('/mepco_entrance.jpg') no-repeat center center fixed;
      background-size: cover;
      color: #1e293b;
      min-height: 100vh;
      padding: 30px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
    }}
    .directory-card {{
      width: 100%;
      max-width: 980px;
      background: #ffffff;
      border-radius: 6px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
      padding: 32px 36px;
      border-top: 6px solid #0022cc;
    }}
    .dir-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #0022cc;
      padding-bottom: 18px;
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 14px;
    }}
    .dir-title h1 {{ font-size: 20px; font-weight: 800; color: #0022cc; }}
    .dir-title p {{ font-size: 12.5px; color: #64748b; font-weight: 600; margin-top: 3px; }}

    .dir-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .btn-action {{
      padding: 8px 16px;
      border-radius: 4px;
      font-size: 12.5px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: none;
      transition: all 0.15s;
    }}
    .btn-action:hover {{ transform: translateY(-1px); }}
    .btn-batch {{ background: #0284c7; color: #fff; }}
    .btn-batch:hover {{ background: #0369a1; }}
    .btn-back {{ background: #475569; color: #fff; }}
    .btn-back:hover {{ background: #334155; }}

    .controls-strip {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 18px;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .search-input {{
      flex: 1;
      min-width: 260px;
      height: 38px;
      padding: 8px 14px;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      font-size: 13.5px;
      outline: none;
    }}
    .search-input:focus {{ border-color: #0077ff; box-shadow: 0 0 0 2px rgba(0,119,255,0.15); }}
    .stats-pill {{
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      padding: 8px 14px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
      color: #1d4ed8;
    }}

    .batch-banner {{
      display: none;
      background: #f0fdf4;
      border: 1.5px solid #86efac;
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 18px;
      font-size: 13px;
      color: #166534;
      font-weight: 700;
    }}

    .students-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .students-table th {{
      background: #0022cc;
      color: #fff;
      padding: 9px 10px;
      font-size: 12px;
      font-weight: 700;
      text-align: left;
    }}
    .students-table td {{
      padding: 9px 12px;
      border-bottom: 1px solid #e2e8f0;
    }}
    .students-table tr:hover {{
      background: #f8fafc;
    }}
    .badge-pass {{
      background: #dcfce7;
      color: #15803d;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 800;
    }}
    .badge-fail {{
      background: #fee2e2;
      color: #b91c1c;
      padding: 2px 8px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 800;
    }}
    .btn-view-res {{
      background: #eff6ff;
      color: #0077ff;
      border: 1px solid #bfdbfe;
      padding: 4px 10px;
      border-radius: 3px;
      text-decoration: none;
      font-weight: 700;
      font-size: 11.5px;
      transition: all 0.15s;
    }}
    .btn-view-res:hover {{
      background: #0077ff;
      color: #fff;
    }}
    {COLLEGE_DETAIL_STYLE}
  </style>
</head>
<body>

  <div class="directory-card">
    <div class="dir-header">
      <div class="dir-title">
        <h1>MEPCO SCHLENK ENGINEERING COLLEGE (AUTONOMOUS)</h1>
        <p>End Semester Examinations — All Students Database Directory (May 2026)</p>
      </div>
      <div class="dir-actions">
        <button class="btn-action btn-batch" onclick="runBatchTest()" id="btnRunBatch">⚡ Test All 130 via TCP</button>
        <a href="/" class="btn-action btn-back">← Portal Login</a>
      </div>
    </div>

    <div id="batchBanner" class="batch-banner">
      Testing all 130 students via Adaptive Sliding Window TCP Server on port 65433...
    </div>

    <div class="controls-strip">
      <input type="text" id="filterInput" class="search-input" placeholder="🔍 Search by Roll Number (e.g. 1025), Name, or Branch..." oninput="filterStudents()">
      <div class="stats-pill" id="statsPill">130 Sample Student Records</div>
    </div>

    <div class="table-scroll" role="region" aria-label="Student records" tabindex="0"><table class="students-table">
      <thead>
        <tr>
          <th style="width: 14%; text-align: center;">Roll Number</th>
          <th style="width: 25%;">Student Name</th>
          <th style="width: 27%;">Branch</th>
          <th style="width: 10%; text-align: center;">GPA</th>
          <th style="width: 10%; text-align: center;">Status</th>
          <th style="width: 14%; text-align: center;">Action</th>
        </tr>
      </thead>
      <tbody id="studentsTbody">
        {rows}
      </tbody>
    </table>
  </div>

  </div>
  <script>
    function filterStudents() {{
      const query = document.getElementById('filterInput').value.toLowerCase().trim();
      const rows = document.querySelectorAll('.student-row');
      let visible = 0;
      rows.forEach(r => {{
        const text = r.getAttribute('data-search') || '';
        if (text.includes(query)) {{
          r.style.display = '';
          visible++;
        }} else {{
          r.style.display = 'none';
        }}
      }});
      document.getElementById('statsPill').innerText = `Showing: ${{visible}} of 130 Students`;
    }}

    function runBatchTest() {{
      const banner = document.getElementById('batchBanner');
      const btn = document.getElementById('btnRunBatch');
      banner.style.display = 'block';
      banner.innerText = '⚡ Connecting to TCP Server port 65433... Querying 130 students concurrently...';
      btn.disabled = true;

      fetch('/api/batch_test_all', {{headers: {{'X-Demo-Token': '{correction_lab.DEMO_TOKEN}'}}}})
        .then(r => r.json())
        .then(data => {{
          btn.disabled = false;
          banner.style.background = '#f0fdf4';
          banner.style.color = '#15803d';
          banner.innerHTML = `✔ <strong>Batch Test Complete!</strong> Tested <strong>${{data.total}}</strong> students in <strong>${{data.time_sec.toFixed(2)}}s</strong> (${{data.qps.toFixed(1)}} queries/sec). <strong>${{data.success_count}}/${{data.total}} successful results.</strong>`;
        }})
        .catch(err => {{
          btn.disabled = false;
          banner.innerText = 'Batch test completed over TCP.';
        }});
    }}
  </script>
</body>
</html>"""


# ============================================================================
# HTTP SERVER ROUTING & API IMPLEMENTATION
# ============================================================================
class PortalHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        params = urllib.parse.parse_qs(url.query)

        # 1. Main Home Portal Page
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PORTAL_PAGE.encode('utf-8'))

        # 2. SEPARATE Dedicated Result Certificate Page (/result?roll=...)
        elif path == "/result":
            roll_number = normalize_roll(params.get("roll", ["24BAD025"])[0])

            res = resolve_result(roll_number, server.PUBLICATIONS, CACHED_RESULTS,
                lambda: request_student_result(roll_number))
            with server.PUBLICATIONS.lock:
                res = guard_result(roll_number, res, server.PUBLICATIONS)
                html_result = generate_result_page(roll_number, res)
            status = 200 if res["success"] else 404 if res["status_message"] == "RECORD_NOT_FOUND" else 503
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html_result.encode('utf-8'))

        elif path == "/demo":
            if not self._demo_allowed():
                self._json({"error": "The correction lab is available only on this computer"}, 403)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(correction_lab.page().encode())

        elif path == "/api/demo/status":
            if not self._demo_allowed():
                self._json({"error": "Local demonstration only"}, 403)
                return
            store = server.PUBLICATIONS
            with store.lock:
                self._json({"available": store.available,
                            "current": store.snapshot("24BAD025") if store.available else None,
                            "counters": dict(store.counters), "events": copy.deepcopy(store.events)})

        # Local college reference assets: the preview works without external CDNs.
        elif path in {
            '/college-background.jpg', '/college-logo.gif',
            '/poppins-400.ttf', '/poppins-500.ttf', '/poppins-700.ttf'
        }:
            asset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path[1:])
            if os.path.isfile(asset_path):
                self.send_response(200)
                mime = 'image/jpeg' if path.endswith('.jpg') else 'image/gif' if path.endswith('.gif') else 'font/ttf'
                self.send_header('Content-Type', mime)
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                with open(asset_path, 'rb') as asset:
                    self.wfile.write(asset.read())
            else:
                self.send_response(404)
                self.end_headers()

        # 3. Crest Logo
        elif path == "/mepco_crest.png":
            if os.path.exists(CREST_IMAGE_PATH):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(CREST_IMAGE_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        # Campus Background Image (Login Page)
        elif path == "/mepco_campus.jpg":
            if os.path.exists(CAMPUS_IMAGE_PATH):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                with open(CAMPUS_IMAGE_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        # Entrance Monument Background Image (Result Page)
        elif path == "/mepco_entrance.jpg":
            if os.path.exists(ENTRANCE_IMAGE_PATH):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                with open(ENTRANCE_IMAGE_PATH, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        # 4. Asynchronous Query Start (Returns Session ID)
        elif path == "/api/query_start":
            cleanup_completed_sessions()
            roll_number = normalize_roll(params.get("roll", ["24BAD025"])[0])
            session_id = str(uuid.uuid4())

            metrics = server.get_live_metrics()
            q_len = metrics.get("queue_length", 0)
            act_w = metrics.get("active_window", 0)
            w_size = metrics.get("window_size", 10)
            delay = metrics.get("processing_delay", 0.20)

            # Check if sliding window has free capacity (queue empty or light load)
            if act_w < w_size and q_len == 0:
                initial_pos = 0
                est_wait = 0.2
                status_init = "ACTIVE_PROCESSING"
            else:
                initial_pos = q_len + 1
                est_wait = server.estimate_wait_seconds(initial_pos, w_size, delay)
                status_init = "QUEUED"

            with SESSIONS_LOCK:
                QUERY_SESSIONS[session_id] = {
                    "roll_number": roll_number,
                    "position": initial_pos,
                    "total_queued": max(1, initial_pos),
                    "estimated_sec": est_wait,
                    "active_window": act_w,
                    "window_size": w_size,
                    "status": status_init,
                    "done": False,
                    "result": None
                }

            def query_worker():
                def queue_callback(pos, total, status):
                    m = server.get_live_metrics()
                    d = m.get("processing_delay", 0.20)
                    w = m.get("window_size", 10)
                    if pos == 0:
                        est = 0.0
                    else:
                        est = server.estimate_wait_seconds(pos, w, d)

                    with SESSIONS_LOCK:
                        if session_id in QUERY_SESSIONS:
                            QUERY_SESSIONS[session_id]["position"] = pos
                            QUERY_SESSIONS[session_id]["total_queued"] = total
                            QUERY_SESSIONS[session_id]["estimated_sec"] = est
                            QUERY_SESSIONS[session_id]["active_window"] = m.get("active_window", 0)
                            QUERY_SESSIONS[session_id]["window_size"] = w
                            QUERY_SESSIONS[session_id]["status"] = status

                try:
                    res = request_student_result(
                        roll_number=roll_number,
                        timeout=15.0,
                        queue_callback=queue_callback
                    )
                except Exception as e:
                    res = {"success": False, "status_message": str(e), "result_data": None}

                res = guard_result(roll_number, res, server.PUBLICATIONS)
                with server.PUBLICATIONS.lock:
                    if res.get("success"):
                        CACHED_RESULTS[(EXAM_ID, roll_number)] = (copy.deepcopy(res), time.monotonic())
                with SESSIONS_LOCK:
                    if session_id in QUERY_SESSIONS:
                        QUERY_SESSIONS[session_id]["done"] = True
                        QUERY_SESSIONS[session_id]["completed_at"] = time.monotonic()
                        QUERY_SESSIONS[session_id]["result"] = res
                        QUERY_SESSIONS[session_id]["position"] = 0
                        QUERY_SESSIONS[session_id]["status"] = "COMPLETED"


            t = threading.Thread(target=query_worker, daemon=True)
            t.start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"session_id": session_id}).encode('utf-8'))

        # 5. Query Progress Poll
        elif path == "/api/query_poll":
            session_id = params.get("session_id", [""])[0]
            with SESSIONS_LOCK:
                raw = QUERY_SESSIONS.get(session_id)
                sess = copy.deepcopy(raw) if raw else {"done": True, "position": 0,
                         "result": {"success": False, "status_message": "SESSION_NOT_FOUND"}}
            if sess.get("done") and raw:
                sess["result"] = guard_result(sess.get("roll_number", ""),
                                              sess.get("result"), server.PUBLICATIONS)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(sess).encode('utf-8'))

        # 6. Live Telemetry Endpoint
        elif path == "/api/telemetry":
            metrics = server.get_live_metrics()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(metrics).encode('utf-8'))

        # 7. Burst Load Simulation (Spawn 25 concurrent student TCP clients)
        elif path == "/api/simulate_burst":
            if not self._demo_allowed() or self.headers.get("X-Demo-Token") != correction_lab.DEMO_TOKEN:
                self._json({"error": "Local demonstration authorization required"}, 403)
                return
            try:
                count = int(params.get("count", ["25"])[0])
                if count not in (25, 50, 100):
                    raise ValueError()
            except ValueError:
                self._json({"error": "Choose 25, 50, or 100 sample students"}, 400)
                return

            def burst_worker():
                threads = []
                for i in range(count):
                    r_num = f"24BAD{1 + (i % 130):03d}"
                    th = threading.Thread(
                        target=client.request_result,
                        kwargs={'roll_number': r_num, 'host': '127.0.0.1', 'port': TCP_SERVER_PORT, 'verbose': False},
                        daemon=True
                    )
                    threads.append(th)
                    th.start()
                    time.sleep(0.005)  # Flash crowd: concurrent queries hit port 65433 at once
                for th in threads:
                    th.join(timeout=10.0)

            threading.Thread(target=burst_worker, daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "burst_count": count}).encode('utf-8'))

        # 8. Set Demo Mode (normal vs slowmo)
        elif path == "/api/set_mode":
            if not self._demo_allowed() or self.headers.get("X-Demo-Token") != correction_lab.DEMO_TOKEN:
                self._json({"error": "Local demonstration authorization required"}, 403)
                return
            mode_name = params.get("mode", ["normal"])[0]
            new_metrics = server.set_demo_mode(mode_name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "metrics": new_metrics}).encode('utf-8'))

        # 9. Direct JSON Query Endpoint
        elif path == "/api/query":
            roll_number = normalize_roll(params.get("roll", ["24BAD025"])[0])

            res = resolve_result(roll_number, server.PUBLICATIONS, CACHED_RESULTS,
                lambda: request_student_result(roll_number),
                force=params.get("force", ["0"])[0] == "1")
            status = 200 if res["success"] else 404 if res["status_message"] == "RECORD_NOT_FOUND" else 503
            self._json(res, status)

        # 10. All Students Directory Page
        elif path == "/students":
            if not self._demo_allowed():
                self._json({"error": "Not found"}, 404)
                return
            html_dir = generate_students_directory_page()
            self.send_response(200 if server.PUBLICATIONS.available else 503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html_dir.encode('utf-8'))

        # 11. Batch Test All Students API
        elif path == "/api/batch_test_all":
            if not self._demo_allowed() or self.headers.get("X-Demo-Token") != correction_lab.DEMO_TOKEN:
                self._json({"error": "Local demonstration authorization required"}, 403)
                return
            t0 = time.time()
            success_count = 0
            rolls = [f"24BAD{i:03d}" for i in range(1, 131)]

            def fetch_single(roll):
                try:
                    return client.request_result(
                        roll,
                        host='127.0.0.1',
                        port=TCP_SERVER_PORT,
                        timeout=8.0,
                        verbose=False
                    )
                except Exception:
                    return {"success": False}

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                res_list = list(executor.map(fetch_single, rolls))
                for r in res_list:
                    if r and r.get("success"):
                        success_count += 1

            elapsed = time.time() - t0

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "total": 130,
                "success_count": success_count,
                "time_sec": elapsed,
                "qps": 130 / max(0.01, elapsed)
            }).encode('utf-8'))

        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data, status=200):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _demo_allowed(self):
        return DEMO_ENABLED and ipaddress.ip_address(self.client_address[0]).is_loopback

    def do_POST(self):
        if self.path != "/api/demo/action":
            self._json({"error": "Not found"}, 404)
            return
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if (not self._demo_allowed() or self.headers.get("X-Demo-Token") != correction_lab.DEMO_TOKEN
                or (origin is not None and origin != "http://" + host)):
            self._json({"error": "Local demonstration authorization required"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 or self.headers.get("Content-Type") != "application/json":
                raise ValueError("A small JSON action is required")
            data = json.loads(self.rfile.read(length))
            action = data.get("action") if isinstance(data, dict) else None
            store = server.PUBLICATIONS
            with store.lock:
                if action == "prepare":
                    record = store.publish_mark("24BAD025", "Computer Networks", 38)
                    CACHED_RESULTS[(EXAM_ID, "24BAD025")] = (
                        {"success": True, "result_data": record, "delivery_source": "demo_seeded_cache"},
                        time.monotonic())
                    message = f"Published 38 marks as v{record['result_version']}. Older result cached."
                elif action == "correct":
                    record = store.publish_mark("24BAD025", "Computer Networks", 43)
                    message = f"Published correction: 43 marks, v{record['result_version']}. Old cache retained for testing."
                elif action == "stale":
                    store.arm_stale_reply("24BAD025")
                    message = "The next version-aware TCP request for 24BAD025 will receive an older CRC-valid reply once."
                elif action == "fail":
                    store.fail_once.add("24BAD025")
                    message = "The next TCP delivery for 24BAD025 will fail. Current published-snapshot fallback can be tested."
                elif action == "toggle_authority":
                    store.available = not store.available
                    message = "Verification restored." if store.available else "Verification paused. Unverified results must be blocked."
                else:
                    raise ValueError("Unknown demonstration action")
            self._json({"success": True, "message": message})
        except (ValueError, VerificationUnavailable) as exc:
            self._json({"error": str(exc)}, 400)

    def log_message(self, format, *args):
        return


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    request_queue_size = 256


def run_portal():
    print("\n" + "=" * 70)
    print("  🏛️ MEPCO SCHLENK PORTAL (LIVE QUEUE TELEMETRY) ACTIVE")
    print(f"  👉 Portal Login (Laptop):  http://localhost:{WEB_PORT}")
    print("  Local preview only; no college website or database connection.")
    print(f"  👉 Direct Result:          http://localhost:{WEB_PORT}/result?roll=24BAD025")
    print("=" * 70 + "\n")

    # Start Adaptive Sliding Window TCP Server on 65433
    server_thread = threading.Thread(
        target=server.start_server,
        kwargs={'mode': 'adaptive', 'port': TCP_SERVER_PORT, 'window_size': 10},
        daemon=True
    )
    server_thread.start()
    time.sleep(0.5)

    with ThreadingHTTPServer(('127.0.0.1', WEB_PORT), PortalHTTPHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down web portal...")


if __name__ == "__main__":
    run_portal()
