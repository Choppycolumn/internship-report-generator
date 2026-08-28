from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from src.daily_material_reader import (
    list_review_dates,
    load_daily_review,
    save_daily_review,
    validate_date,
)
from src.daily_report_generator import (
    approve_daily_draft,
    fully_approve_daily_draft,
    generate_daily_draft,
    load_daily_draft,
    save_daily_draft,
)
from src.image_analyzer import hash_distance
from src.image_processor import MAX_UPLOAD_BYTES, process_uploaded_image
from src.models import DailyDraft, DailyImageReview, DailyReview
from src.paths import ProjectPaths, get_paths


MAX_REQUEST_BYTES = 80 * 1024 * 1024


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>每日实习图片与文字审核</title>
  <style>
    :root { color-scheme: light; --ink:#172036; --muted:#65708a; --line:#dbe1ec; --blue:#1f5eff; --bg:#f4f6fa; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Microsoft YaHei","PingFang SC",sans-serif; color:var(--ink); background:var(--bg); }
    header { background:linear-gradient(125deg,#172d62,#214fc1); color:white; padding:28px max(24px,calc((100% - 1180px)/2)); }
    header h1 { margin:0 0 8px; font-size:26px; }
    header p { margin:0; opacity:.82; }
    main { max-width:1180px; margin:24px auto; padding:0 20px 60px; }
    .panel,.card { background:white; border:1px solid var(--line); border-radius:14px; box-shadow:0 4px 18px rgba(30,45,80,.06); }
    .panel { padding:20px; margin-bottom:20px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
    label { display:block; font-size:13px; color:var(--muted); margin-bottom:7px; }
    input,textarea,select,button { font:inherit; }
    input[type=date],input[type=text],select,textarea { width:100%; border:1px solid #cbd3e2; border-radius:9px; padding:10px 12px; background:white; }
    textarea { resize:vertical; min-height:78px; line-height:1.65; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:14px; }
    button,.file-button { border:0; border-radius:9px; padding:10px 16px; cursor:pointer; background:#e9eefb; color:#16336f; font-weight:600; }
    button.primary { background:var(--blue); color:white; }
    button.danger { color:#a51d2d; background:#ffecef; }
    input[type=file] { max-width:100%; }
    #cards { display:grid; gap:18px; }
    .card { overflow:hidden; display:grid; grid-template-columns:minmax(260px,42%) 1fr; }
    .photo { min-height:280px; background:#101521; display:flex; align-items:center; justify-content:center; }
    .photo img { width:100%; height:100%; max-height:520px; object-fit:contain; }
    .content { padding:20px; }
    .card-head { display:flex; justify-content:space-between; gap:10px; align-items:center; margin-bottom:12px; }
    .name { font-weight:700; word-break:break-all; }
    .quality { font-size:12px; color:var(--muted); background:#f2f5fa; padding:8px 10px; border-radius:8px; margin:10px 0; line-height:1.55; }
    .field { margin-top:12px; }
    .approved { display:flex; gap:8px; align-items:center; color:#33415f; font-size:14px; }
    .approved input { width:auto; }
    .empty { text-align:center; padding:42px; color:var(--muted); border:1px dashed #b9c3d7; border-radius:14px; background:white; }
    #status { min-height:24px; color:#2351a7; font-size:14px; }
    .notice { background:#fff8df; border:1px solid #f1dda0; color:#695316; padding:10px 12px; border-radius:9px; margin-top:12px; font-size:13px; }
    .panel h2 { margin:0 0 8px; font-size:20px; }
    .panel-intro { color:var(--muted); font-size:13px; margin:0 0 16px; }
    .fact-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:16px; }
    .fact-box { padding:12px; border:1px solid var(--line); border-radius:10px; background:#fafbfe; }
    .fact-box textarea { min-height:105px; background:white; }
    .metric-row { display:flex; flex-wrap:wrap; gap:10px; margin:14px 0; }
    .metric { padding:8px 11px; border-radius:8px; background:#eef3ff; color:#234c9c; font-size:13px; }
    .draft-warning { padding:8px 10px; margin:7px 0; border-radius:8px; background:#fff4dc; color:#785717; font-size:13px; }
    #draftSections { display:grid; gap:10px; margin-top:14px; }
    .draft-section { border:1px solid var(--line); border-radius:10px; padding:12px; background:#fcfdff; }
    .draft-section-head { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:8px; color:#4e5c78; font-size:12px; }
    .draft-section textarea { min-height:105px; }
    .draft-section input[type=text] { width:100%; border:1px solid #cbd3e2; border-radius:8px; padding:9px 10px; }
    .locked { color:#1c6a42; background:#e8f8ef; border:1px solid #b8e6ca; padding:10px 12px; border-radius:9px; font-weight:600; }
    @media (max-width:780px) { .grid,.fact-grid,.card { grid-template-columns:1fr; } .photo { min-height:220px; } }
  </style>
</head>
<body>
<header>
  <h1>每日实习图片与文字审核</h1>
  <p>照片、图题和对应文字逐项保存。系统生成的文字应在此确认后才能进入正式报告。</p>
</header>
<main>
  <section class="panel">
    <div class="grid">
      <div><label for="date">日期</label><input id="date" type="date"></div>
      <div><label for="existingDates">已保存日期</label><select id="existingDates"><option value="">选择日期…</option></select></div>
      <div><label for="topic">当日主题</label><input id="topic" type="text" placeholder="例如：设备生产与检测流程学习"></div>
      <div><label for="statusSelect">审核状态</label><select id="statusSelect"><option value="draft">草稿</option><option value="reviewed">已检查</option><option value="approved">已确认</option></select></div>
    </div>
    <div class="field"><label for="notes">当日简单记录</label><textarea id="notes" placeholder="记录参观内容、工作人员介绍、观察到的流程，以及不能写入的内容。"></textarea></div>
    <div class="actions">
      <input id="files" type="file" accept="image/jpeg,image/png,image/tiff,image/webp" multiple>
      <button id="captionDraft">填充图题草稿</button>
      <button id="load" type="button">打开该日期</button>
      <button id="save" class="primary" type="button">保存审核内容</button>
    </div>
    <div class="actions" aria-label="日期导航与批准">
      <button id="previousDay" type="button">前一天</button>
      <button id="nextDay" type="button">后一天</button>
      <button id="fullyApproveDay" class="primary" type="button" title="确认当天全部内容并锁定">批准</button>
    </div>
    <div class="notice">原图保存在 attachments/originals；处理图用于排版。自动质量判断只是提示，仍需人工确认隐私、人物授权和图片内容。</div>
    <div id="status"></div>
  </section>
  <section class="panel" id="draftPanel">
    <h2>结构化草稿与事实审核</h2>
    <p class="panel-intro">无需外部模型 API：上传后可以在 Codex 中说“生成 YYYY-MM-DD”，草稿会直接写回这里。下方按钮只生成不虚构事实的安全框架。</p>
    <div class="actions">
      <button id="generateDraft" type="button">生成安全草稿框架</button>
      <button id="saveDraft" type="button">保存草稿修改</button>
    </div>
    <div id="draftMessage" class="panel-intro">尚未加载草稿。</div>
    <div id="draftEditor" hidden>
      <div class="field"><label for="draftTitle">草稿标题</label><input id="draftTitle" type="text"></div>
      <div class="fact-grid">
        <div class="fact-box"><label for="confirmedFacts">已确认事实（每行一项）</label><textarea id="confirmedFacts"></textarea></div>
        <div class="fact-box"><label for="inferredFacts">合理推断（不会自动进入正文）</label><textarea id="inferredFacts"></textarea></div>
        <div class="fact-box"><label for="pendingFacts">待确认内容（批准前必须清空）</label><textarea id="pendingFacts"></textarea></div>
        <div class="fact-box"><label for="prohibitedClaims">禁止写入内容（每行一项）</label><textarea id="prohibitedClaims"></textarea></div>
      </div>
      <div id="draftMetrics" class="metric-row"></div>
      <div id="draftWarnings"></div>
      <div id="draftSections"></div>
    </div>
  </section>
  <section id="cards"></section>
</main>
<script>
const $ = s => document.querySelector(s);
let images = [];
let draft = null;
let savedDates = [];
const today = new Date();
$('#date').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

function qualityText(q, duplicateOf) {
  if (!q) return '保存后显示分辨率、清晰度和亮度检查。';
  const warnings = q.warnings?.length ? q.warnings.join('、') : '无自动警告';
  return `${q.width_px}×${q.height_px}px；清晰度 ${q.blur_score.toFixed(1)}；亮度 ${q.brightness_mean.toFixed(1)}；${warnings}${duplicateOf ? `；疑似重复：${duplicateOf}` : ''}`;
}

function render() {
  const root = $('#cards'); root.innerHTML='';
  if (!images.length) { root.innerHTML='<div class="empty">尚未添加照片。选择多张图片后，会在这里逐张显示，并在下方填写对应文字。</div>'; return; }
  images.forEach((item,index) => {
    const card=document.createElement('article'); card.className='card';
    const photo=document.createElement('div'); photo.className='photo';
    const img=document.createElement('img'); img.src=item.preview; img.alt=item.caption||item.original_name; photo.appendChild(img);
    const content=document.createElement('div'); content.className='content';
    const head=document.createElement('div'); head.className='card-head';
    const name=document.createElement('div'); name.className='name'; name.textContent=`图 ${index+1} · ${item.original_name}`;
    const remove=document.createElement('button'); remove.className='danger'; remove.textContent='移除'; remove.onclick=()=>{images.splice(index,1);render();};
    head.append(name,remove); content.appendChild(head);
    const quality=document.createElement('div'); quality.className='quality'; quality.textContent=qualityText(item.quality,item.duplicate_of); content.appendChild(quality);
    const caption=document.createElement('div'); caption.className='field';
    caption.innerHTML='<label>图题</label>'; const captionInput=document.createElement('input'); captionInput.type='text'; captionInput.value=item.caption||''; captionInput.placeholder=`图${index+1} 现场照片`; captionInput.oninput=e=>item.caption=e.target.value; caption.appendChild(captionInput); content.appendChild(caption);
    const text=document.createElement('div'); text.className='field'; text.innerHTML='<label>与该图片对应的生成文字</label>';
    const textArea=document.createElement('textarea'); textArea.value=item.generated_text||''; textArea.placeholder='系统生成的相关段落会显示在这里；你也可以直接修改。'; textArea.oninput=e=>item.generated_text=e.target.value; text.appendChild(textArea); content.appendChild(text);
    const approve=document.createElement('label'); approve.className='approved field'; const box=document.createElement('input'); box.type='checkbox'; box.checked=!!item.approved; box.onchange=e=>item.approved=e.target.checked; approve.append(box,document.createTextNode('该图片、图题和文字已核对')); content.appendChild(approve);
    card.append(photo,content); root.appendChild(card);
  });
}

function lines(value) { return value.split(/\r?\n/).map(item=>item.trim()).filter(Boolean); }

function renderDraft() {
  const editor=$('#draftEditor');
  const locked=draft?.status==='approved';
  editor.hidden=!draft;
  $('#saveDraft').disabled=!draft||locked;
  $('#fullyApproveDay').disabled=!draft||locked;
  if(!draft){$('#draftMessage').textContent='尚未加载草稿。';return;}
  $('#draftMessage').innerHTML=locked?'<div class="locked">该日期草稿已经批准并锁定。</div>':`草稿版本 ${draft.version} · 置信度 ${(draft.confidence*100).toFixed(0)}%`;
  $('#draftTitle').value=draft.title||''; $('#draftTitle').disabled=locked;
  $('#confirmedFacts').value=(draft.facts.confirmed_facts||[]).join('\n');
  $('#inferredFacts').value=(draft.facts.inferred_facts||[]).join('\n');
  $('#pendingFacts').value=(draft.facts.pending_confirmation||[]).join('\n');
  $('#prohibitedClaims').value=(draft.facts.prohibited_claims||[]).join('\n');
  for(const id of ['confirmedFacts','inferredFacts','pendingFacts','prohibitedClaims']) $('#'+id).disabled=locked;
  const m=draft.metrics||{};
  $('#draftMetrics').innerHTML=`<span class="metric">正文 ${m.body_characters||0} 字</span><span class="metric">目标 ${m.target_characters||draft.word_count_target} 字</span><span class="metric">还差 ${m.remaining_characters||0} 字</span><span class="metric">最高相似度 ${((m.max_similarity||0)*100).toFixed(0)}%</span>`;
  const warnings=$('#draftWarnings'); warnings.innerHTML='';
  (draft.content_warnings||[]).forEach(value=>{const item=document.createElement('div');item.className='draft-warning';item.textContent=value;warnings.appendChild(item);});
  const root=$('#draftSections'); root.innerHTML='';
  (draft.sections||[]).forEach((section,index)=>{
    const box=document.createElement('div');box.className='draft-section';
    const head=document.createElement('div');head.className='draft-section-head';
    head.innerHTML=`<span>${index+1}. ${section.type} · ${section.id}</span><span>${(m.section_characters||{})[section.id]||0} 字</span>`;box.appendChild(head);
    if(section.type==='heading'){
      const input=document.createElement('input');input.type='text';input.value=section.text||'';input.disabled=locked;input.oninput=e=>section.text=e.target.value;box.appendChild(input);
    }else if(section.type==='paragraph'){
      const area=document.createElement('textarea');area.value=section.text||'';area.disabled=locked;area.oninput=e=>section.text=e.target.value;box.appendChild(area);
    }else{
      const path=document.createElement('div');path.className='quality';path.textContent=section.path||'';box.appendChild(path);
      const caption=document.createElement('input');caption.type='text';caption.value=section.caption||'';caption.disabled=locked;caption.oninput=e=>section.caption=e.target.value;box.appendChild(caption);
    }
    const confirm=document.createElement('label');confirm.className='approved field';const check=document.createElement('input');check.type='checkbox';check.checked=!!section.requires_confirmation;check.disabled=locked;check.onchange=e=>section.requires_confirmation=e.target.checked;confirm.append(check,document.createTextNode('该段仍需要确认'));box.appendChild(confirm);root.appendChild(box);
  });
}

function readFile(file) { return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);}); }
$('#files').addEventListener('change', async e => {
  for (const file of e.target.files) images.push({original_name:file.name,data_url:await readFile(file),preview:URL.createObjectURL(file),caption:'',generated_text:'',approved:false});
  e.target.value=''; render();
});

async function loadDates() {
  const response=await fetch('/api/dates'); const data=await response.json();
  savedDates=[...(data.dates||[])].sort();
  const select=$('#existingDates'); select.innerHTML='<option value="">选择日期…</option>';
  data.dates.forEach(date=>{const option=document.createElement('option');option.value=date;option.textContent=date;select.appendChild(option);});
}
$('#existingDates').onchange=e=>{if(e.target.value){$('#date').value=e.target.value;loadDay();}};

async function loadDay() {
  const date=$('#date').value; if(!date) return;
  $('#status').textContent='正在读取…';
  const response=await fetch(`/api/day?date=${encodeURIComponent(date)}`); const data=await response.json();
  if(!response.ok){$('#status').textContent=data.error||'读取失败';return;}
  $('#topic').value=data.topic||''; $('#notes').value=data.notes||''; $('#statusSelect').value=data.status||'draft';
  images=(data.images||[]).map(item=>({...item,preview:item.image_url})); render();
  const draftResponse=await fetch(`/api/draft?date=${encodeURIComponent(date)}`); const draftData=await draftResponse.json();
  draft=draftResponse.ok?draftData.draft:null; renderDraft(); $('#status').textContent=`已打开 ${date}，共 ${images.length} 张图片。`;
  $('#existingDates').value=date;
}
$('#load').onclick=loadDay;

async function navigateReport(direction) {
  if(!savedDates.length) return;
  const current=$('#date').value;
  const index=savedDates.indexOf(current);
  let nextIndex;
  if(index>=0) nextIndex=index+direction;
  else if(direction<0) nextIndex=savedDates.filter(value=>value<current).length-1;
  else nextIndex=savedDates.findIndex(value=>value>current);
  if(nextIndex<0||nextIndex>=savedDates.length) {
    $('#status').textContent=direction<0?'已经是第一份报告。':'已经是最后一份报告。';
    return;
  }
  $('#date').value=savedDates[nextIndex];
  await loadDay();
}
$('#previousDay').onclick=()=>navigateReport(-1);
$('#nextDay').onclick=()=>navigateReport(1);

$('#captionDraft').onclick=()=>{
  const topic=$('#topic').value.trim()||'当日实习';
  images.forEach((item,index)=>{if(!item.caption)item.caption=`图${index+1} ${topic}相关现场照片`;});render();
};

async function saveReview(){
  const payload={date:$('#date').value,topic:$('#topic').value,notes:$('#notes').value,status:$('#statusSelect').value,images:images.map(item=>({id:item.id,original_name:item.original_name,data_url:item.data_url,caption:item.caption,generated_text:item.generated_text,approved:item.approved}))};
  $('#status').textContent='正在保存并检查图片…'; $('#save').disabled=true;
  try {
    const response=await fetch('/api/save-day',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); const data=await response.json();
    if(!response.ok) throw new Error(data.error||'保存失败');
    images=data.review.images.map(item=>({...item,preview:item.image_url})); render(); await loadDates(); $('#status').textContent=`保存成功：${data.review.date}，${images.length} 张图片。`;return data.review;
  } catch(error) { $('#status').textContent=error.message;throw error; } finally { $('#save').disabled=false; }
}
$('#save').onclick=()=>saveReview().catch(()=>{});

function syncDraftFields(){
  draft.title=$('#draftTitle').value.trim();
  draft.facts.confirmed_facts=lines($('#confirmedFacts').value);
  draft.facts.inferred_facts=lines($('#inferredFacts').value);
  draft.facts.pending_confirmation=lines($('#pendingFacts').value);
  draft.facts.prohibited_claims=lines($('#prohibitedClaims').value);
}

async function saveDraftChanges(){
  if(!draft||draft.status==='approved') return draft;
  syncDraftFields(); $('#draftMessage').textContent='正在保存草稿…';
  const response=await fetch('/api/save-draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({draft})});const data=await response.json();
  if(!response.ok) throw new Error(data.error||'草稿保存失败');draft=data.draft;renderDraft();return draft;
}

$('#generateDraft').onclick=async()=>{try{await saveReview();const response=await fetch('/api/generate-draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:$('#date').value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'草稿生成失败');draft=data.draft;renderDraft();}catch(error){$('#draftMessage').textContent=error.message;}};
$('#saveDraft').onclick=async()=>{try{await saveDraftChanges();}catch(error){$('#draftMessage').textContent=error.message;}};
$('#fullyApproveDay').onclick=async()=>{
  if(!draft||draft.status==='approved') return;
  if(!window.confirm('批准后当天内容将被完全确认并锁定，是否继续？')) return;
  try{
    images.forEach(item=>item.approved=true);
    $('#statusSelect').value='reviewed';
    $('#pendingFacts').value='';
    draft.facts.pending_confirmation=[];
    (draft.sections||[]).forEach(section=>section.requires_confirmation=false);
    render();
    await saveReview();
    await saveDraftChanges();
    const response=await fetch('/api/fully-approve-draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:$('#date').value})});
    const data=await response.json();
    if(!response.ok) throw new Error(data.error||'批准失败');
    draft=data.draft;
    $('#statusSelect').value='approved';
    renderDraft();
    $('#status').textContent=`${$('#date').value} 已完全批准并锁定。`;
    await loadDates();
  }catch(error){$('#draftMessage').textContent=error.message;}
};
async function bootstrap() {
  await loadDates();
  const requestedDate=new URLSearchParams(window.location.search).get('date');
  if(requestedDate){$('#date').value=requestedDate;await loadDay();}
  else {render();renderDraft();}
}
bootstrap();
</script>
</body>
</html>"""


def _review_payload(review: DailyReview) -> dict:
    payload = review.model_dump(mode="json")
    for item in payload["images"]:
        filename = Path(item["processed_path"]).name
        item["image_url"] = f"/media/{quote(review.date)}/{quote(filename)}?v={quote(review.updated_at)}"
    return payload


def _draft_payload(draft: DailyDraft) -> dict:
    return draft.model_dump(mode="json")


def _save_payload(paths: ProjectPaths, payload: dict) -> DailyReview:
    date = validate_date(str(payload.get("date", "")))
    existing = load_daily_review(paths, date)
    existing_by_id = {item.id: item for item in existing.images}
    saved_images: list[DailyImageReview] = []
    next_index = 1
    for incoming in payload.get("images", []):
        image_id = incoming.get("id")
        if image_id and image_id in existing_by_id and not incoming.get("data_url"):
            image = existing_by_id[image_id].model_copy(deep=True)
            image.caption = str(incoming.get("caption", ""))
            image.generated_text = str(incoming.get("generated_text", ""))
            image.approved = bool(incoming.get("approved", False))
            saved_images.append(image)
            continue
        data_url = str(incoming.get("data_url", ""))
        match = re.fullmatch(r"data:image/[a-zA-Z0-9.+-]+;base64,(.+)", data_url, re.DOTALL)
        if not match:
            raise ValueError("New images must contain a valid image data URL")
        data = base64.b64decode(match.group(1), validate=True)
        while (paths.root / "days" / date / f"photo_{next_index:02d}.jpg").exists():
            next_index += 1
        image = process_uploaded_image(
            paths,
            date,
            next_index,
            str(incoming.get("original_name", f"photo_{next_index:02d}")),
            data,
            caption=str(incoming.get("caption", "")),
            generated_text=str(incoming.get("generated_text", "")),
        )
        image.approved = bool(incoming.get("approved", False))
        saved_images.append(image)
        next_index += 1

    for index, image in enumerate(saved_images):
        for previous in saved_images[:index]:
            if image.quality.sha256 == previous.quality.sha256 or hash_distance(
                image.quality.perceptual_hash, previous.quality.perceptual_hash
            ) <= 4:
                image.duplicate_of = previous.id
                if "POSSIBLE_DUPLICATE" not in image.quality.warnings:
                    image.quality.warnings.append("POSSIBLE_DUPLICATE")
                break
    review = DailyReview(
        date=date,
        topic=str(payload.get("topic", "")),
        notes=str(payload.get("notes", "")),
        status=str(payload.get("status", "draft")),
        images=saved_images,
        updated_at=existing.updated_at,
    )
    save_daily_review(paths, review)
    return load_daily_review(paths, date)


def make_handler(paths: ProjectPaths):
    class Handler(BaseHTTPRequestHandler):
        server_version = "InternshipDailyReview/1.1"

        def log_message(self, format: str, *args) -> None:
            print(f"[daily-review] {self.address_string()} - {format % args}")

        def _send_json(self, payload: dict, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                data = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/api/dates":
                self._send_json({"dates": list_review_dates(paths)})
                return
            if parsed.path == "/api/health":
                self._send_json({"ok": True, "service": "daily-review"})
                return
            if parsed.path == "/api/day":
                try:
                    date = parse_qs(parsed.query).get("date", [""])[0]
                    self._send_json(_review_payload(load_daily_review(paths, date)))
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 400)
                return
            if parsed.path == "/api/draft":
                try:
                    date = parse_qs(parsed.query).get("date", [""])[0]
                    self._send_json({"draft": _draft_payload(load_daily_draft(paths, date))})
                except FileNotFoundError as exc:
                    self._send_json({"error": str(exc)}, 404)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, 400)
                return
            if parsed.path.startswith("/media/"):
                parts = [unquote(part) for part in parsed.path.split("/") if part]
                if len(parts) != 3:
                    self.send_error(404)
                    return
                _, date, filename = parts
                try:
                    validate_date(date)
                except ValueError:
                    self.send_error(404)
                    return
                if Path(filename).name != filename:
                    self.send_error(404)
                    return
                file_path = paths.root / "days" / date / filename
                if not file_path.is_file():
                    self.send_error(404)
                    return
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path not in {
                "/api/save-day",
                "/api/generate-draft",
                "/api/save-draft",
                "/api/approve-draft",
                "/api/fully-approve-draft",
            }:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("Request is empty or exceeds 80 MB")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if path == "/api/save-day":
                    review = _save_payload(paths, payload)
                    self._send_json({"ok": True, "review": _review_payload(review)})
                elif path == "/api/generate-draft":
                    draft = generate_daily_draft(
                        paths,
                        str(payload.get("date", "")),
                        payload.get("target_characters"),
                    )
                    self._send_json({"ok": True, "draft": _draft_payload(draft)})
                elif path == "/api/save-draft":
                    draft = DailyDraft.model_validate(payload.get("draft"))
                    saved = save_daily_draft(paths, draft)
                    self._send_json({"ok": True, "draft": _draft_payload(saved)})
                elif path == "/api/approve-draft":
                    draft = approve_daily_draft(paths, str(payload.get("date", "")))
                    self._send_json({"ok": True, "draft": _draft_payload(draft)})
                else:
                    draft = fully_approve_daily_draft(paths, str(payload.get("date", "")))
                    self._send_json({"ok": True, "draft": _draft_payload(draft)})
            except Exception as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return Handler


def serve(paths: ProjectPaths, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(paths))
    server.daemon_threads = True
    print(f"Daily review app: http://{host}:{port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="每日实习图片与文字审核网页")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the review page in the default browser")
    args = parser.parse_args()
    if args.open:
        threading.Timer(0.7, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()
    serve(get_paths(), args.host, args.port)


if __name__ == "__main__":
    main()
