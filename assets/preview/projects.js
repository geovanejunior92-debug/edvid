const projects = document.getElementById('projects');
const notice = document.getElementById('notice');
let items = [];
const labels = {ready:'DISPONÍVEL PARA REVISÃO',missing:'LOCALIZAR VÍDEO',processing:'PROCESSANDO',waiting:'AGUARDANDO CORTE',error:'PRECISA DE ATENÇÃO'};
function el(tag, text, cls) {const node=document.createElement(tag); if(text)node.textContent=text; if(cls)node.className=cls;return node;}
const ICON={
 pin:'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.3l1.9 4 4.4.6-3.2 3.1.8 4.4L8 11.3l-3.9 2.1.8-4.4L1.7 5.9l4.4-.6z"/></svg>',
 rename:'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M11.6 1.9l2.5 2.5-8 8L3 13l.6-3.1zM2 14.6h12v1.1H2z"/></svg>',
 archive:'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.6 2.6h12.8v2.6H1.6zM2.8 6.4h10.4v7H2.8zm2.6 2.1h5.2v1.2H5.4z"/></svg>',
 restore:'<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2.6a5.4 5.4 0 105.1 7.1h-1.7A3.8 3.8 0 118 4.2v2.1l3-2.8L8 .6z"/></svg>'};
function iconButton(label,svg,on,pressed){
 const b=el('button',null,'act');b.type='button';b.innerHTML=svg;b.title=label;b.setAttribute('aria-label',label);
 if(pressed!==undefined)b.setAttribute('aria-pressed',String(!!pressed));
 b.addEventListener('click',on);return b;}
async function update(id,patch){
 const response=await fetch('/api/projects/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,...patch})});
 const result=await response.json().catch(()=>({}));
 if(!response.ok)throw new Error(result.error||'Não foi possível atualizar o projeto');
 return result;}
function apply(id,patch,onError){
 const item=items.find(p=>p.id===id);if(!item)return;const before={...item};
 Object.assign(item,patch);render();
 update(id,patch).catch(error=>{Object.assign(item,before);render();notice.textContent=error.message;if(onError)onError(error);});}
function startRename(card,project){
 const heading=card.querySelector('h2');const input=el('input',null,'rename');input.value=project.name;input.maxLength=100;
 const finish=(commit)=>{if(!input.isConnected)return;const name=input.value.trim();input.replaceWith(heading);
  if(commit&&name&&name!==project.name)apply(project.id,{name});};
 input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();finish(true);}else if(e.key==='Escape'){e.preventDefault();finish(false);}});
 input.addEventListener('blur',()=>finish(true));
 heading.replaceWith(input);input.focus();input.select();}
function card(p){
 const card=el('article',null,'card');if(p.pinned)card.classList.add('pinned');const poster=el('div',null,'poster');
 if(p.thumbnail){const img=el('img');img.src=p.thumbnail;img.alt='Prévia do projeto';img.loading='lazy';poster.append(img);}else poster.textContent='▶';
 const body=el('div',null,'body');const status=el('span',labels[p.status]||p.status,'status');status.dataset.status=p.status;
 body.append(status,el('h2',p.name),el('p',p.message));
 if(p.updatedAt){body.append(el('time','Atualizado em '+new Date(p.updatedAt*1000).toLocaleDateString('pt-BR')));}
 const link=el('a','Continuar edição');link.href=`/p/${p.id}/`;body.append(link);
 const acts=el('div',null,'acts');
 if(p.archived){acts.append(iconButton('Tirar do arquivo',ICON.restore,()=>apply(p.id,{archived:false})));}
 else{
  acts.append(iconButton(p.pinned?'Desafixar projeto':'Fixar projeto no topo',ICON.pin,()=>apply(p.id,{pinned:!p.pinned}),p.pinned));
  acts.append(iconButton('Renomear projeto',ICON.rename,()=>startRename(card,p)));
  acts.append(iconButton('Arquivar — esconde o cartão, não apaga nenhum arquivo',ICON.archive,()=>archiveWithUndo(p)));}
 body.append(acts);card.append(poster,body);return card;}
// Archiving is reversible and touches no file, but it should not cost a hunt
// through a disclosure to undo a mis-click: the way back is offered right where
// the card disappeared from.
function archiveWithUndo(p){
 apply(p.id,{archived:true});
 notice.replaceChildren(document.createTextNode(`“${p.name}” foi arquivado. Nenhum arquivo foi apagado. `));
 const undo=el('button','Desfazer','undo');undo.type='button';
 undo.addEventListener('click',()=>apply(p.id,{archived:false}));
 notice.append(undo);}
function render(){
 const view=EdvidProjectsModel.libraryView(items,document.getElementById('search').value);
 projects.replaceChildren();
 notice.textContent=view.visible.length?`${view.visible.length} projeto(s)`:(view.archived.length?'Nenhum projeto ativo. Veja os arquivados abaixo.':'Nenhum projeto encontrado.');
 for(const p of view.visible)projects.append(card(p));
 const box=document.getElementById('archived');const list=document.getElementById('archived-list');
 box.hidden=!view.archived.length;
 document.getElementById('archived-count').textContent=`Arquivados (${view.archived.length})`;
 list.replaceChildren();for(const p of view.archived)list.append(card(p));}
document.getElementById('search').addEventListener('input',render);
fetch('/api/projects').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{items=data.projects;render();}).catch(()=>notice.textContent='Não foi possível carregar os projetos. Recarregue para tentar novamente.');
const IMPORT_STATE = 'edvid-import-v1';
let savedImport = null;
try { savedImport = JSON.parse(sessionStorage.getItem(IMPORT_STATE) || 'null'); } catch (_) { sessionStorage.removeItem(IMPORT_STATE); }
let importProject = savedImport?.project || null, importedCount = savedImport?.importedCount || 0, importing = false;
const requestKey = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
const saveImport = (stage, extra={}) => sessionStorage.setItem(IMPORT_STATE, JSON.stringify({version:1,stage,project:importProject,importedCount,...extra}));
const clearImport = () => { importProject = null; importedCount = 0; savedImport = null; sessionStorage.removeItem(IMPORT_STATE); document.getElementById('import-continue').hidden = true; };
const newVideos = document.getElementById('new-videos');
newVideos.addEventListener('change', clearImport);
document.getElementById('new-name').addEventListener('input', clearImport);
async function resumeImport(){
 if(!savedImport?.project)return;
 const status=document.getElementById('import-status');const link=document.getElementById('import-continue');link.href=savedImport.project.url+'?sources=1';link.hidden=false;
 if(savedImport.stage==='confirmed'){location.assign(link.href);return;}
 if(savedImport.stage!=='requesting'||!savedImport.request){status.textContent='Um envio anterior foi interrompido. Continue com os vídeos já importados ou selecione os arquivos novamente.';return;}
 importing=true;for(const id of ['new-submit','new-name','new-videos'])document.getElementById(id).disabled=true;
 try{
  status.textContent='Confirmando o corte automático já enviado…';
  const response=await fetch(savedImport.project.url+'api/requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(savedImport.request)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Não foi possível confirmar o corte automático');
  saveImport('confirmed',{request:savedImport.request});location.assign(link.href);
 }catch(error){status.textContent=error.message+' O pedido continuará disponível para nova tentativa.';}
 finally{importing=false;for(const id of ['new-submit','new-name','new-videos'])document.getElementById(id).disabled=false;}
}
document.getElementById('new-project').addEventListener('submit', async event => {
 event.preventDefault(); if(importing)return;
 const files=Array.from(newVideos.files); const status=document.getElementById('import-status');
 if(!files.length)return;
 if(files.some(f=>!f.size||f.size>8*1024**3||!/\.(mp4|mov|m4v|webm)$/i.test(f.name))){status.textContent='Use vídeos MOV, MP4, M4V ou WEBM de até 8 GB por arquivo.';return;}
 importing=true;
 for(const id of ['new-submit','new-name','new-videos'])document.getElementById(id).disabled=true;
 try{
  if(!importProject){
   const response=await fetch('/api/projects/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('new-name').value})});
   const result=await response.json();if(!response.ok)throw new Error(result.error||'Não foi possível criar o projeto');importProject=result;
   saveImport('uploading');
  }
  const link=document.getElementById('import-continue');link.href=importProject.url+'?sources=1';link.hidden=false;
  for(;importedCount<files.length;){
   const file=files[importedCount];status.textContent=`Copiando ${importedCount+1} de ${files.length}: ${file.name}…`;
   const response=await fetch(importProject.url+'api/import',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file});
   const result=await response.json();if(!response.ok)throw new Error(result.error||'Falha ao importar vídeo');
   importedCount++;saveImport('uploading');
  }
  const sourceResponse=await fetch(importProject.url+'api/sources');const sourceResult=await sourceResponse.json();
  if(!sourceResponse.ok)throw new Error(sourceResult.error||'Não foi possível preparar o corte');
  const idempotencyKey=savedImport?.request?.idempotencyKey||requestKey();
  const automatic=EdvidProjectsModel.automaticRequest(sourceResult.sources,idempotencyKey);
  if(automatic){
   savedImport={version:1,stage:'requesting',project:importProject,importedCount,request:automatic};saveImport('requesting',{request:automatic});
   status.textContent='Vídeo enviado. Iniciando transcrição e primeiro corte…';
   const requestResponse=await fetch(importProject.url+'api/requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(automatic)});
   const requestResult=await requestResponse.json();if(!requestResponse.ok)throw new Error(requestResult.error||'Não foi possível iniciar o corte automático');
   saveImport('confirmed',{request:automatic});
   status.textContent='Transcrição e primeiro corte iniciados. Abrindo projeto…';
  }else{sessionStorage.removeItem(IMPORT_STATE);status.textContent='Vídeos importados. Escolha a estratégia do corte no projeto…';}
  location.assign(importProject.url+'?sources=1');
 }catch(error){status.textContent=error.message+' Os arquivos já importados foram preservados. Você pode tentar novamente.';}
 finally{importing=false;for(const id of ['new-submit','new-name','new-videos'])document.getElementById(id).disabled=false;}
});
resumeImport();
