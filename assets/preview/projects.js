const projects = document.getElementById('projects');
const notice = document.getElementById('notice');
let items = [];
const labels = {ready:'DISPONÍVEL PARA REVISÃO',missing:'LOCALIZAR VÍDEO',processing:'PROCESSANDO',waiting:'AGUARDANDO CORTE',error:'PRECISA DE ATENÇÃO'};
function el(tag, text, cls) {const node=document.createElement(tag); if(text)node.textContent=text; if(cls)node.className=cls;return node;}
function render(){
 const query=document.getElementById('search').value.toLocaleLowerCase();projects.replaceChildren();
 const visible=items.filter(p=>p.name.toLocaleLowerCase().includes(query));
 notice.textContent=visible.length ? `${visible.length} projeto(s)` : 'Nenhum projeto encontrado.';
 for(const p of visible){const card=el('article',null,'card');const poster=el('div',null,'poster');
 if(p.thumbnail){const img=el('img');img.src=p.thumbnail;img.alt='Prévia do projeto';img.loading='lazy';poster.append(img);}else poster.textContent='▶';
 const body=el('div',null,'body');const status=el('span',labels[p.status]||p.status,'status');status.dataset.status=p.status;
 body.append(status,el('h2',p.name),el('p',p.message));
 if(p.updatedAt){const time=el('time','Atualizado em '+new Date(p.updatedAt*1000).toLocaleDateString('pt-BR'));body.append(time);}
 const link=el('a','Continuar edição');link.href=`/p/${p.id}/`;body.append(link);card.append(poster,body);projects.append(card);}}
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
