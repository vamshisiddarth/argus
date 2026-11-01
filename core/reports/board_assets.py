"""
CSS and JavaScript of the static board report.

Both are inlined into one HTML file and allowed by hash in its Content Security
Policy, so there are no inline style attributes, no event-handler attributes and
no outside requests anywhere. LOGIC_JS is pure (no DOM) so Node can test it.
"""

from __future__ import annotations

_LIGHT = (
    "--bg:#eef1ef;--surface:#ffffff;--surface-2:#f4f6f5;--ink:#15201c;"
    "--muted:#4b5a54;--line:#cdd5d0;--accent:#0b5a6b;--accent-soft:#dff0f3;"
    "--easy:#1b6a3f;--easy-soft:#e1f1e8;--doubt:#8a5200;--doubt-soft:#fbefd9;"
    "--keep:#475569;--keep-soft:#e8edf2;--bad:#a8361f;--bad-soft:#f9e3df;"
    "--on-solid:#ffffff;"
)
_DARK = (
    "--bg:#0d1312;--surface:#151d1c;--surface-2:#1b2625;--ink:#e6ede9;"
    "--muted:#a6b5af;--line:#2c3a37;--accent:#6bc0d2;--accent-soft:#16333a;"
    "--easy:#63cc92;--easy-soft:#163223;--doubt:#e8b055;--doubt-soft:#38290f;"
    "--keep:#a9b8c8;--keep-soft:#222c37;--bad:#ee8a75;--bad-soft:#3c1e18;"
    "--on-solid:#0d1312;"
)

LOGO_INNER = (
    '<circle cx="24" cy="24" r="22" fill="#2a2a3e" stroke="#8b8fff" stroke-width="3"/>'
    '<circle cx="24" cy="24" r="16.5" fill="white"/>'
    '<circle cx="24" cy="24" r="9.5" fill="#3b2a1a"/>'
    '<circle cx="24" cy="24" r="5.5" fill="#1a0f0a"/>'
    '<circle cx="20" cy="20" r="2.8" fill="white"/>'
    '<circle cx="27" cy="28" r="1.2" fill="white" opacity="0.6"/>'
    '<ellipse cx="15" cy="14" rx="4" ry="2" fill="white" opacity="0.25" '
    'transform="rotate(-30 15 14)"/>'
)
LOGO_SVG = (
    '<svg class="logo-mark" viewBox="0 0 48 48" width="30" height="30" '
    f'aria-hidden="true" focusable="false">{LOGO_INNER}</svg>'
)

CSS = (
    ":root{"
    + _LIGHT
    + "--tally-h:4rem;color-scheme:light}\n"
    + '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){'
    + _DARK
    + "color-scheme:dark}}\n"
    + ':root[data-theme="dark"]{'
    + _DARK
    + "color-scheme:dark}\n"
    + """
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%}
body{margin:0;overflow-wrap:anywhere;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
h1,h2,h3,p{margin:0}
.mono,.v,.num,td.n{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:-999px;top:0;background:var(--accent);color:var(--on-solid);padding:8px 12px;z-index:50}
.skip:focus{left:8px;top:8px}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
a{color:var(--accent)}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.muted{color:var(--muted)}
.topbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 20px;padding:10px 16px;background:var(--surface);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px}
.logo{font-size:22px;font-weight:800;letter-spacing:-.01em;color:var(--ink)}
.logo-mark{display:block;flex:none}
.topbar h1{font-size:17px;font-weight:600;padding-left:14px;border-left:2px solid var(--line)}
.topbar .meta{color:var(--muted);flex:1 1 20rem}
.btn{font:inherit;font-weight:600;padding:6px 12px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);cursor:pointer}
.btn:hover{border-color:var(--accent)}
.tally{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:stretch;gap:1px;background:var(--line);border-bottom:1px solid var(--line)}
.totals{display:flex;flex:1 1 auto;flex-wrap:wrap;gap:1px}
.totals .t{flex:1 1 11rem;background:var(--surface);padding:8px 16px;display:flex;flex-direction:column;gap:2px;min-width:0}
.tally .v{font-size:19px;font-weight:600}
.tally .s{font-size:12px;color:var(--muted)}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 16px;background:var(--surface)}
.pos{color:var(--easy)}
.warn{color:var(--doubt)}
section{padding:16px 16px 4px}
section>h2{font-size:20px;margin-bottom:12px;display:flex;gap:10px;align-items:baseline}
.num{font-size:12px;color:var(--muted)}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px}
.kpis>.kpi{flex:1 1 13rem}
.kpi,.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;min-width:0}
.kpi .v{display:block;font-size:clamp(20px,2vw,24px);font-weight:600;line-height:1.2}
.kpi .v small{font-size:12px;font-weight:400;color:var(--muted)}
.kpi .s{display:block;color:var(--muted);font-size:12.5px}
.kpi.alert .v{color:var(--bad)}
.panels{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px}
.panels>.panel{flex:1 1 22rem}
.banner{background:var(--doubt-soft);color:var(--ink);border:1px solid var(--doubt);border-radius:8px;padding:10px 14px;margin-bottom:12px}
.banner ul{margin:4px 0 0;padding-left:20px}
.panel hr{border:0;border-top:1px solid var(--line);margin:12px 0 4px}
.panel h3{font-size:15px;margin-bottom:8px}
.panel ul,.panel ol{margin:6px 0 0;padding-left:20px}
.panel li{margin:2px 0}
.bar{display:block;width:100%;height:18px;border-radius:4px;background:var(--surface-2)}
.bar .b-billed{fill:var(--easy)}
.bar .b-list{fill:var(--accent)}
.bar .b-model{fill:var(--doubt)}
.bar .b-run{fill:var(--accent)}
.bar .b-over{fill:var(--bad)}
.big{font-size:22px;font-weight:600;margin-bottom:6px}
.big small{font-size:12px;font-weight:400;color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 0;padding:0;list-style:none}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.sw-billed{background:var(--easy)}
.sw-list{background:var(--accent)}
.sw-model{background:var(--doubt)}
.lane-row{display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-top:1px solid var(--line)}
.lane-row:first-of-type{border-top:0}
.dashboard{display:grid;grid-template-columns:minmax(15rem,19rem) 1fr;gap:16px;align-items:start}
.rail{position:sticky;top:calc(var(--tally-h) + 8px);max-height:calc(100vh - var(--tally-h) - 16px);overflow:auto;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:10px}
.rail h3{font-size:15px}
.rail label{font-size:12px;color:var(--muted);display:block;margin-bottom:2px}
.rail input,.rail select{width:100%;font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.fchip{font:inherit;font-size:12.5px;padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--ink);cursor:pointer}
.fchip[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,22rem),1fr));gap:12px;align-items:start}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;display:grid;grid-template-columns:6px 1fr;overflow:hidden;min-width:0}
.card[hidden]{display:none}
.stripe{background:var(--keep)}
.card[data-lane="easy"] .stripe{background:var(--easy)}
.card[data-lane="doubt"] .stripe{background:var(--doubt)}
.card[data-state="approve"]{border-color:var(--easy)}
.card[data-state="investigate"]{border-color:var(--doubt)}
.card[data-state="keep"]{border-color:var(--keep)}
.body{padding:12px 14px;display:flex;flex-direction:column;gap:8px;min-width:0}
.card-top{display:flex;flex-wrap:wrap;gap:4px 12px;justify-content:space-between;align-items:flex-start}
.card-top h3{font-size:15px;flex:1 1 12rem;min-width:0;overflow-wrap:anywhere}
.range{font-size:16px;font-weight:600;white-space:nowrap}
.range small{font-size:11.5px;font-weight:400;color:var(--muted)}
.row{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center}
.pill,.bchip{display:inline-block;font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;letter-spacing:.03em}
.pill-easy{background:var(--easy-soft);color:var(--easy)}
.pill-doubt{background:var(--doubt-soft);color:var(--doubt)}
.pill-flat{background:var(--keep-soft);color:var(--keep)}
.pill-bad{background:var(--bad-soft);color:var(--bad)}
.chip-billed{background:var(--easy-soft);color:var(--easy)}
.chip-list{background:var(--accent-soft);color:var(--accent)}
.chip-model{background:var(--doubt-soft);color:var(--doubt)}
.chip-unpriced{background:var(--bad-soft);color:var(--bad)}
.risk{font-size:13px}
.risk b{color:var(--bad)}
details.more{border-top:1px solid var(--line);padding-top:6px}
details.more summary{cursor:pointer;color:var(--accent);font-weight:600}
details.more h4{margin:8px 0 2px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
details.more ul,details.more ol{margin:2px 0 0;padding-left:20px}
.tablewrap{overflow-x:auto;margin-top:6px;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--surface-2);color:var(--muted);font-weight:600;position:sticky;top:0}
td.n,th.n{text-align:right}
tr:last-child td{border-bottom:0}
.decide{display:flex;flex-direction:column;gap:6px;border-top:1px solid var(--line);padding-top:8px}
.seg{display:inline-flex;flex-wrap:wrap;border:1px solid var(--line);border-radius:6px;overflow:hidden;align-self:flex-start}
.seg button{font:inherit;font-size:12.5px;font-weight:600;padding:6px 12px;border:0;border-right:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
.seg button:last-child{border-right:0}
.seg button[aria-pressed="true"][data-v="approve"]{background:var(--easy);color:var(--on-solid)}
.seg button[aria-pressed="true"][data-v="investigate"]{background:var(--doubt);color:var(--on-solid)}
.seg button[aria-pressed="true"][data-v="keep"]{background:var(--keep);color:var(--on-solid)}
.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:6px}
.fields label{display:block;font-size:11.5px;color:var(--muted)}
.fields input{width:100%;font:inherit;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink)}
.hint{font-size:12px;color:var(--doubt)}
.empty{padding:24px;text-align:center;color:var(--muted);background:var(--surface);border:1px dashed var(--line);border-radius:8px}
.jump{font-size:12px}
.foot{padding:12px 16px 24px;color:var(--muted);font-size:12px}
.about{margin-bottom:8px}
.about summary{cursor:pointer;color:var(--accent);font-weight:600}
.about ul{margin:6px 0 0;padding-left:20px}
.about li{margin:3px 0;max-width:110ch}
@media (max-width:1200px){.dashboard{grid-template-columns:1fr}.rail{position:static;max-height:none;flex-direction:row;flex-wrap:wrap;align-items:flex-end}.rail>*{flex:1 1 14rem}.rail>h3{flex-basis:100%}}
@media (max-width:900px){.tally{position:static}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media print{.rail,.tally,.decide,.topbar .btn,.skip{display:none}.card{break-inside:avoid}}
"""
)

LOGIC_JS = """
var BoardLogic=(function(){
'use strict';
var STATES={approve:1,investigate:1,keep:1};
function fmtUsd(n){
  var v=Number(n)||0;
  var s=v===0?'0':(Math.abs(v)>=100?Math.round(v).toLocaleString('en-US'):v.toFixed(2));
  return '$'+s;
}
function computeTally(opps,decisions){
  var t={approved:{low:0,high:0,count:0},investigating:{low:0,high:0,count:0},
    kept:{count:0,withoutReason:0},undecided:0,totalHigh:0,shareOfHigh:0};
  opps.forEach(function(o){
    t.totalHigh+=o.high;
    var d=decisions&&decisions[o.id];
    if(!d||!STATES[d.state]){t.undecided++;return;}
    if(d.state==='approve'){t.approved.low+=o.low;t.approved.high+=o.high;t.approved.count++;}
    else if(d.state==='investigate'){t.investigating.low+=o.low;t.investigating.high+=o.high;t.investigating.count++;}
    else{t.kept.count++;if(!String(d.note||'').trim()){t.kept.withoutReason++;}}
  });
  t.shareOfHigh=t.totalHigh>0?t.approved.high/t.totalHigh:0;
  return t;
}
function csvCell(v){
  var s=v===null||v===undefined?'':String(v);
  if(/^[=+\\-@\\t\\r]/.test(s)){s="'"+s;}
  if(/[",\\n\\r]/.test(s)){s='"'+s.replace(/"/g,'""')+'"';}
  return s;
}
function toCsv(rows){
  return rows.map(function(r){return r.map(csvCell).join(',');}).join('\\r\\n')+'\\r\\n';
}
function clip(v,n){return String(v===undefined||v===null?'':v).slice(0,n);}
function normalize(d){
  if(!d||!STATES[d.state]){return null;}
  return {state:d.state,note:clip(d.note,1000),owner:clip(d.owner,200),
    expires:clip(d.expires,10),decided_at:clip(d.decided_at,40)};
}
function normalizeAll(map){
  var out={};
  Object.keys(map||{}).forEach(function(id){
    var n=normalize(map[id]);
    if(n){out[id]=n;}
  });
  return out;
}
function parseImport(text){
  var obj;
  try{obj=JSON.parse(text);}catch(e){return {ok:false,error:'The file is not valid JSON.'};}
  if(!obj||obj.schema!=='argus-board-decisions/1'||!Array.isArray(obj.decisions)){
    return {ok:false,error:'This is not an Argus board decisions file.'};
  }
  var map={};
  obj.decisions.forEach(function(d){
    if(d&&typeof d.opportunity_id==='string'){
      var n=normalize(d);
      if(n){map[clip(d.opportunity_id,64)]=n;}
    }
  });
  return {ok:true,decisions:map,scan_id:clip(obj.scan_id,64)};
}
function mergeDecisions(current,incoming){
  var out={};
  Object.keys(current||{}).forEach(function(id){out[id]=current[id];});
  Object.keys(incoming||{}).forEach(function(id){
    var have=out[id];
    if(!have||String(incoming[id].decided_at)>String(have.decided_at)){out[id]=incoming[id];}
  });
  return out;
}
function matches(o,d,f){
  var state=d&&STATES[d.state]?d.state:null;
  var chip=f.chip;
  if(chip==='easy'&&o.lane!=='easy'){return false;}
  if(chip==='doubt'&&o.lane!=='doubt'){return false;}
  if(chip==='undecided'&&state){return false;}
  if((chip==='approve'||chip==='investigate'||chip==='keep')&&state!==chip){return false;}
  if(f.action&&f.action!=='all'&&o.action!==f.action){return false;}
  var words=String(f.query||'').toLowerCase().split(/\\s+/).filter(Boolean);
  for(var i=0;i<words.length;i++){if(o.search.indexOf(words[i])<0){return false;}}
  return true;
}
return {fmtUsd:fmtUsd,computeTally:computeTally,csvCell:csvCell,toCsv:toCsv,
  normalizeAll:normalizeAll,parseImport:parseImport,mergeDecisions:mergeDecisions,matches:matches};
})();
"""

UI_JS = """
(function(){
'use strict';
var L=BoardLogic;
var data=JSON.parse(document.getElementById('board-data').textContent);
var KEY='argus-board-decisions-v1',TKEY='argus-board-theme';
var root=document.documentElement;
var cards=[].slice.call(document.querySelectorAll('article.card'));
var byId={};
data.opportunities.forEach(function(o){byId[o.id]=o;});
var filter={chip:'all',action:'all',query:''};
var decisions=load();

function $(id){return document.getElementById(id);}
function load(){
  try{var raw=localStorage.getItem(KEY);if(raw){return L.normalizeAll(JSON.parse(raw));}}catch(e){}
  return {};
}
function save(){try{localStorage.setItem(KEY,JSON.stringify(decisions));}catch(e){}}
function say(msg){$('status').textContent=msg;}

function applyTheme(mode){
  if(mode==='light'||mode==='dark'){root.setAttribute('data-theme',mode);}
  else{root.removeAttribute('data-theme');}
  var dark=mode==='dark'||(mode!=='light'&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);
  $('theme').textContent=dark?'Switch to light theme':'Switch to dark theme';
}
function initTheme(){
  var mode='auto';
  var m=/theme=(light|dark)/.exec(location.hash);
  if(m){mode=m[1];}
  else{try{mode=localStorage.getItem(TKEY)||'auto';}catch(e){}}
  applyTheme(mode);
}
function toggleTheme(){
  var dark=root.getAttribute('data-theme')==='dark'||(!root.getAttribute('data-theme')&&window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches);
  var next=dark?'light':'dark';
  try{localStorage.setItem(TKEY,next);}catch(e){}
  applyTheme(next);
}

function paintCard(card){
  var id=card.getAttribute('data-id');
  var d=decisions[id]||null;
  var state=d?d.state:'';
  if(state){card.setAttribute('data-state',state);}else{card.removeAttribute('data-state');}
  [].forEach.call(card.querySelectorAll('button[data-v]'),function(b){
    b.setAttribute('aria-pressed',b.getAttribute('data-v')===state?'true':'false');
  });
  var owner=card.querySelector('.f-owner'),note=card.querySelector('.f-note'),exp=card.querySelector('.f-expires');
  var expL=card.querySelector('.f-expires-l'),hint=card.querySelector('.hint');
  if(document.activeElement!==owner){owner.value=d?d.owner:'';}
  if(document.activeElement!==note){note.value=d?d.note:'';}
  if(document.activeElement!==exp){exp.value=d?d.expires:'';}
  var isKeep=state==='keep';
  expL.hidden=!isKeep;exp.hidden=!isKeep;
  var missing=isKeep&&!String(d.note||'').trim();
  hint.hidden=!missing;
  hint.textContent=missing?'Keep needs a reason. Write one in the note.':'';
}

function render(){
  cards.forEach(function(card){
    var o=byId[card.getAttribute('data-id')];
    paintCard(card);
    card.hidden=!L.matches(o,decisions[o.id],filter);
  });
  var shown=cards.filter(function(c){return !c.hidden;}).length;
  $('count').textContent='Showing '+shown+' of '+cards.length+' opportunities';
  var empty=$('no-match');
  if(empty){empty.hidden=shown!==0||cards.length===0;}
  var t=L.computeTally(data.opportunities,decisions);
  var range=function(x){return x.low===x.high?L.fmtUsd(x.high):L.fmtUsd(x.low)+' to '+L.fmtUsd(x.high);};
  $('t-approved').textContent=t.approved.count?range(t.approved):'$0';
  $('t-approved-s').textContent=t.approved.count?(t.approved.count+' approved, '+L.fmtUsd(t.approved.high*12)+' a year at most, '+Math.round(t.shareOfHigh*100)+'% of the total'):'Nothing approved yet';
  $('t-investigating').textContent=t.investigating.count?range(t.investigating):'$0';
  $('t-investigating-s').textContent=t.investigating.count+' under investigation';
  $('t-kept').textContent=String(t.kept.count);
  $('t-kept-s').textContent=t.kept.withoutReason?(t.kept.withoutReason+' without a reason'):'Kept on purpose';
  $('t-undecided').textContent=String(t.undecided);
  $('t-undecided-s').textContent='of '+data.opportunities.length+' opportunities';
  renderKeep();
  root.style.setProperty('--tally-h',$('tally').offsetHeight+'px');
}

function renderKeep(){
  var list=$('keep-list');list.textContent='';
  var n=0;
  data.opportunities.forEach(function(o){
    var d=decisions[o.id];
    if(d&&d.state==='keep'){
      n++;
      var li=document.createElement('li');
      li.textContent=o.title+' - '+(d.note?d.note:'no reason given')+(d.expires?' (until '+d.expires+')':'')+(d.owner?' - owner '+d.owner:'');
      list.appendChild(li);
    }
  });
  $('keep-empty').hidden=n!==0;
}

function setState(id,state){
  var cur=decisions[id];
  if(cur&&cur.state===state){delete decisions[id];}
  else{
    decisions[id]={state:state,note:cur?cur.note:'',owner:cur?cur.owner:'',expires:cur?cur.expires:'',decided_at:new Date().toISOString()};
  }
  save();render();
}
function setField(id,field,value){
  var cur=decisions[id];
  if(!cur){return;}
  cur[field]=value;cur.decided_at=new Date().toISOString();
  save();
  var card=document.getElementById(id);
  if(card){paintCard(card);}
  var t=L.computeTally(data.opportunities,decisions);
  $('t-kept-s').textContent=t.kept.withoutReason?(t.kept.withoutReason+' without a reason'):'Kept on purpose';
  renderKeep();
}

function download(name,type,text){
  var blob=new Blob([text],{type:type});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=name;
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  setTimeout(function(){URL.revokeObjectURL(a.href);},1000);
}
function exportDecisions(){
  var list=Object.keys(decisions).map(function(id){
    var d=decisions[id];
    return {opportunity_id:id,state:d.state,note:d.note,owner:d.owner,expires:d.expires,decided_at:d.decided_at};
  });
  download('argus-board-decisions-'+data.scan_id.slice(0,8)+'.json','application/json',
    JSON.stringify({schema:'argus-board-decisions/1',scan_id:data.scan_id,exported_at:new Date().toISOString(),decisions:list},null,2));
  say('Exported '+list.length+' decisions.');
}
function exportCsv(){
  var rows=[['opportunity_id','title','lane','action','members','low_usd','high_usd','unpriced','decision','owner','note','keep_until']];
  data.opportunities.forEach(function(o){
    var d=decisions[o.id]||{};
    rows.push([o.id,o.title,o.lane,o.action,o.members,o.low,o.high,o.unpriced,d.state||'',d.owner||'',d.note||'',d.expires||'']);
  });
  download('argus-board-'+data.scan_id.slice(0,8)+'.csv','text/csv',L.toCsv(rows));
  say('Exported '+data.opportunities.length+' opportunities to CSV.');
}
function importDecisions(file){
  var reader=new FileReader();
  reader.onload=function(){
    var r=L.parseImport(String(reader.result));
    if(!r.ok){say(r.error);return;}
    var known={},skipped=0;
    Object.keys(r.decisions).forEach(function(id){if(byId[id]){known[id]=r.decisions[id];}else{skipped++;}});
    decisions=L.mergeDecisions(decisions,known);
    save();render();
    say('Imported '+Object.keys(known).length+' decisions'+(skipped?', '+skipped+' skipped (not in this report)':'')+(r.scan_id&&r.scan_id!==data.scan_id?'. They come from a different scan.':'.'));
  };
  reader.readAsText(file);
}

document.addEventListener('click',function(e){
  var t=e.target;
  var dec=t.closest&&t.closest('button[data-v]');
  if(dec){setState(dec.closest('article.card').getAttribute('data-id'),dec.getAttribute('data-v'));return;}
  var chip=t.closest&&t.closest('button[data-chip]');
  if(chip){
    filter.chip=chip.getAttribute('data-chip');
    [].forEach.call(document.querySelectorAll('button[data-chip]'),function(b){b.setAttribute('aria-pressed',b===chip?'true':'false');});
    render();return;
  }
  var id=t.id;
  if(id==='theme'){toggleTheme();}
  else if(id==='export-json'){exportDecisions();}
  else if(id==='export-csv'){exportCsv();}
  else if(id==='clear-all'){
    if(Object.keys(decisions).length&&window.confirm('Clear every decision on this page?')){decisions={};save();render();say('All decisions cleared.');}
  }
  else if(id==='reset-filters'){
    filter={chip:'all',action:'all',query:''};
    $('f-search').value='';$('f-action').value='all';
    [].forEach.call(document.querySelectorAll('button[data-chip]'),function(b){b.setAttribute('aria-pressed',b.getAttribute('data-chip')==='all'?'true':'false');});
    render();
  }
});
document.addEventListener('input',function(e){
  var t=e.target;
  if(t.id==='f-search'){filter.query=t.value;render();return;}
  var card=t.closest&&t.closest('article.card');
  if(!card){return;}
  var id=card.getAttribute('data-id');
  if(t.classList.contains('f-note')){setField(id,'note',t.value);}
  else if(t.classList.contains('f-owner')){setField(id,'owner',t.value);}
  else if(t.classList.contains('f-expires')){setField(id,'expires',t.value);}
});
document.addEventListener('change',function(e){
  var t=e.target;
  if(t.id==='f-action'){filter.action=t.value;render();}
  else if(t.id==='import-file'&&t.files&&t.files[0]){importDecisions(t.files[0]);t.value='';}
});
window.addEventListener('resize',function(){root.style.setProperty('--tally-h',$('tally').offsetHeight+'px');});
initTheme();
render();
})();
"""
