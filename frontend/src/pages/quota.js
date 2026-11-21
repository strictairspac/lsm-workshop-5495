import{quota}from'../stores/quota.js';
import{createSite,listLimits,putLimit,deleteLimit,listBatches,submitBatch,getKeys,getLogs,compactSite,listCompactions}from'../api/quota.js';
import{header}from'../components/common/header.js';
import{table}from'../components/common/table.js';
import{esc,json}from'../utils/html.js';
import{submit,notify}from'../hooks/feedback.js';
import{session}from'../stores/session.js';

export async function quotaPage(el,param){
  await quota.loadSites();
  if(param)quota.select(param);
  const site=quota.current();
  const writable=session.get().role!=='viewer';
  el.innerHTML=header('05','按前缀分配的活键名额，整批判定','嵌套前缀各层独立计数；批次删旧补新按整批写完的活键数判定，覆盖不另占名额。拒绝时整批不变，同 token 重试不重复占名额。')
    +siteNav()
    +(site?await siteView(site,writable):'<div class="empty">还没有站点，先在右侧创建一个站点。</div>')
    +(writable&&!site?createSitePanel():'');
  bindShell(el);
  if(!site)return;
  await refreshAll(el,site.id,writable);
}

function siteNav(){
  return '<div class="slabs">'+quota.sites.map(s=>
    `<a class="slab ${s.id===quota.currentId?'selected':''}" href="#quota/${s.id}"><span class="material-tag">SITE ${s.id}</span><strong>${esc(s.name)}</strong><br><span class="mono muted">${esc(s.code)}</span></a>`
  ).join('')+'</div>';
}

function createSitePanel(){
  return `<section class="panel"><h2>创建站点</h2><form id="site-form">
    <label>站点编码</label><input name="code" required minlength="2" maxlength="64" placeholder="beiling-north">
    <label>站点名称</label><input name="name" required minlength="2" maxlength="120" placeholder="北岭站点-活键名额">
    <label>说明</label><input name="description" maxlength="2000" placeholder="可选">
    <div class="actions"><button class="primary" type="submit">创建站点</button></div></form></section>`;
}

async function siteView(site,writable){
  return `<div class="split">
    <section class="panel">
      <span class="material-tag">OCCUPANCY / 剩余名额</span>
      <h2>${esc(site.name)} <span class="badge mono">${esc(site.code)}</span></h2>
      <p class="muted">${esc(site.description||'')}</p>
      <div id="limits"></div>
      ${writable?`<h3>设置/调整前缀限额</h3><form id="limit-form">
        <label>键名前缀（嵌套前缀各层计数）</label><input name="prefix" required maxlength="64" placeholder="station-a/">
        <label>活键上限（不低于当前占用）</label><input name="limit_value" type="number" min="0" max="100000" required value="4">
        <div class="actions"><button class="primary" type="submit">保存限额</button></div></form>
        <p class="helper">限额只能调到不低于当前占用；删除限额不影响已写入的键。</p>`:''}
    </section>
    <aside class="panel">
      ${writable?createSiteFormInline():''}
      <h3>活键查询</h3>
      <form id="keys-form"><label>按前缀过滤（留空查全部）</label><input name="prefix" maxlength="64" placeholder="station-a/">
      <div class="actions"><button type="submit">查询键值与剩余名额</button></div></form>
      <div id="keys"></div>
      <h3>合并（搬表不改占用）</h3>
      <div class="actions">${writable?'<button id="compact-btn" class="primary">执行日志合并</button>':''} <a href="#" id="refresh-compactions">刷新合并记录</a></div>
      <div id="compactions"></div>
    </aside>
  </div>
  <section class="panel">
    <span class="material-tag">INTERLEAVED BATCHES / 交错写入</span>
    ${writable?`<form id="batch-form" class="form">
      <label>批次幂等 token（重试同 token 返回原判定，不重复占名额）</label><input name="token" required minlength="8" maxlength="80" placeholder="client-uuid-0001">
      <label>有序操作 JSON 数组（put/delete）</label>
      <textarea name="operations" rows="8" required>[
  {"op":"put","key":"station-a/sensor-1","value":"21.0"},
  {"op":"delete","key":"station-a/sensor-2"}
]</textarea>
      <div class="actions"><button class="primary" type="submit">提交整批判定</button></div></form>`:''}
    <p class="helper">按整批写完后的活键数判定；已存在的活键被覆盖不另占名额。拒绝则整批不变，键值与占用一起生效或一起不动。</p>
    <div id="batches"></div>
    <details><summary>查看完整写入日志（LSM 风格追加日志）</summary><div id="logs"></div></details>
  </section>`;
}

function createSiteFormInline(){
  return `<h3>新建站点</h3><form id="site-form">
    <label>编码</label><input name="code" required minlength="2" maxlength="64" placeholder="edge-south">
    <label>名称</label><input name="name" required minlength="2" maxlength="120" placeholder="南坡站点">
    <label>说明</label><input name="description" maxlength="2000">
    <div class="actions"><button type="submit">创建</button></div></form>`;
}

function bindShell(el){
  const f=el.querySelector('#site-form');
  if(f)f.onsubmit=e=>{e.preventDefault();submit(f,async()=>{await createSite(Object.fromEntries(new FormData(f)));notify('站点已创建');quotaPage(el)})};
}

async function refreshAll(el,id,writable){
  const [limits,batches,keys,logs,comps]=await Promise.all([listLimits(id),listBatches(id),getKeys(id),getLogs(id),listCompactions(id)]);
  renderLimits(el,id,limits,writable);
  renderBatches(el,batches);
  renderKeys(el,keys);
  renderLogs(el,logs);
  renderCompactions(el,comps);
  el.querySelector('#limit-form').onsubmit=e=>{e.preventDefault();submit(e.target,async()=>{
    const d=Object.fromEntries(new FormData(e.target));d.limit_value=Number(d.limit_value);
    await putLimit(id,d);notify('限额已保存');await quota.loadSites();refreshAll(el,id,writable);
  })};
  el.querySelector('#keys-form').onsubmit=e=>{e.preventDefault();const p=new FormData(e.target).get('prefix');
    getKeys(id,p||undefined).then(k=>renderKeys(el,k))};
  const bf=el.querySelector('#batch-form');
  if(bf)bf.onsubmit=e=>{e.preventDefault();submit(bf,async()=>{
    const d=Object.fromEntries(new FormData(bf));
    try{d.operations=JSON.parse(d.operations)}catch{throw Error('操作 JSON 格式错误')}
    const r=await submitBatch(id,d);
    notify(r.status==='accepted'?`批次 ${r.token} 已接收（accepted）`:`批次被拒绝：${r.reason||'超出前缀名额'}`);
    await quota.loadSites();quotaPage(el,id);
  })};
  const cb=el.querySelector('#compact-btn');
  if(cb)cb.onclick=()=>submit(cb,async()=>{const r=await compactSite(id);notify(`合并完成：清理 ${r.detail.removed_superseded} 行历史，活键 ${r.live_before}→${r.live_after}`);await quota.loadSites();quotaPage(el,id)});
  el.querySelector('#refresh-compactions').onclick=async e=>{e.preventDefault();renderCompactions(el,await listCompactions(id))};
}

function renderLimits(el,id,rows,writable){
  const box=el.querySelector('#limits');
  box.innerHTML=table(['前缀','上限','已用','剩余','操作'],rows.map(r=>[
    `<span class="mono">${esc(r.prefix)}</span>`,String(r.limit_value),String(r.used),
    `<span class="badge ${r.remaining===0?'failed':r.remaining<=1?'different':'passed'}">${r.remaining}</span>`,
    writable?`<a href="#" data-del="${r.id}" class="danger-link">删除限额</a>`:'—'
  ]));
  box.querySelectorAll('[data-del]').forEach(a=>a.onclick=async e=>{e.preventDefault();
    await deleteLimit(id,Number(a.dataset.del));notify('限额已删除');quotaPage(el,id)});
}

function renderBatches(el,rows){
  el.querySelector('#batches').innerHTML=table(['批次 token','状态','操作数','原因/投影','时间'],rows.map(b=>[
    `<span class="mono">${esc(b.token)}</span>`,
    `<span class="badge ${b.status==='accepted'?'passed':'failed'}">${b.status==='accepted'?'已接收':'已拒绝'}</span>`,
    String(b.operation_count),
    `<details><summary>${esc(b.reason||'查看整批投影键值')}</summary><pre>${json(b.projected)}</pre></details>`,
    esc(b.created_at)
  ]));
}

function renderKeys(el,data){
  const entries=Object.entries(data.values);
  el.querySelector('#keys').innerHTML=`<p class="muted">前缀 <span class="mono">${esc(data.prefix||'(全站)')}</span> · 活键数 <strong>${data.live_count}</strong></p>`
    +(entries.length?table(['键','当前值'],entries.map(([k,v])=>[esc(k),`<span class="mono">${esc(v)}</span>`])):'<div class="empty">该范围内没有存活键（墓碑不返回）。</div>');
}

function renderLogs(el,rows){
  el.querySelector('#logs').innerHTML=table(['seq','键','值/墓碑','层级','批次'],rows.map(r=>[
    String(r.seq),`<span class="mono">${esc(r.key)}</span>`,
    r.deleted?'<span class="badge failed">墓碑</span>':esc(r.value),String(r.level),String(r.batch_id)
  ]));
}

function renderCompactions(el,rows){
  el.querySelector('#compactions').innerHTML=rows.length?table(['时间','合并前行数','合并后行数','活键前→后','清理历史'],rows.map(r=>[
    esc(r.created_at),String(r.rows_before),String(r.rows_after),`${r.live_before} → ${r.live_after}`,String(r.detail.removed_superseded)
  ])):'<p class="helper">尚无合并记录。</p>';
}
