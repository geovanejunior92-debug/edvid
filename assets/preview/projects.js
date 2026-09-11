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
