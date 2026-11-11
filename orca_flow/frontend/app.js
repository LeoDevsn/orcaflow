const app = document.querySelector('#app');
const dialog = document.querySelector('#dialog');
const state = { user: null, data: null, route: '', draft: null, dirty: false, filters: { customers: '', quotes: '', stage: 'Todos' } };
const stages = ['Rascunho', 'Enviado', 'Negociação', 'Aprovado', 'Recusado', 'Arquivado'];
const paths = {
  plus: 'M12 5v14M5 12h14', search: 'M21 21l-4.5-4.5M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0',
  arrow: 'M5 12h14m-6-6 6 6-6 6', back: 'M19 12H5m6-6-6 6 6 6', close: 'M6 6l12 12M18 6 6 18',
  down: 'M12 3v12m-5-5 5 5 5-5M5 16v5h14v-5', trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  check: 'M5 12l4 4L19 6', exit: 'M9 4H4v16h5m5-16h6v16h-6M8 12h12m-4-4 4 4-4 4', help: 'M9 9a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 3h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0'
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.arrow}"/></svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = cents => new Intl.NumberFormat('pt-BR', { style:'currency',currency:'BRL' }).format(Number(cents || 0)/100);
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const afterDays = days => { const d = new Date(); d.setDate(d.getDate()+days); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const date = value => value ? new Intl.DateTimeFormat('pt-BR', { day:'2-digit',month:'short' }).format(new Date(`${value}T12:00:00`)) : '';
const fullDate = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : '';
const b = (text, action, id='', primary=false, extra='') => `<button type="button" class="btn${primary?' primary':''}" data-action="${action}" data-id="${esc(id)}" ${extra}>${text}</button>`;
const empty = (title, text, action='') => `<div class="empty"><h2>${title}</h2><p>${text}</p>${action}</div>`;
const badge = stage => `<span class="badge ${stage==='Aprovado'?'won':stage==='Enviado'||stage==='Negociação'?'sent':stage==='Recusado'?'lost':''}">${esc(stage)}</span>`;
const errorBox = () => '<div class="error" role="alert" tabindex="-1" data-error></div>';

async function api(path, { method='GET', data, form }={}) {
  let response;
  try {
    response = await fetch(`/api/${path}`, { method, credentials:'same-origin', headers: { ...(method!=='GET'?{'X-CSRF-Token':state.user?.csrf || ''}:{}), ...(data?{'Content-Type':'application/json'}:{}) }, body: form || (data?JSON.stringify(data):undefined) });
  } catch { throw new Error('Não foi possível falar com o aplicativo. Confira se a janela do OrçaFlow continua aberta e tente novamente.'); }
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || 'Não foi possível concluir. Tente novamente.'); error.status=response.status; throw error; }
  return result;
}
function toast(message, error=false) {
  const element = document.createElement('div'); element.className=`toast${error?' error-toast':''}`; element.textContent=message;
  document.querySelector('#notifications').append(element); setTimeout(()=>element.remove(), 6500);
}
function showError(form, error) {
  const target = form.querySelector('[data-error]');
  if (target) { target.textContent=error.message; target.focus(); } else toast(error.message,true);
}
async function busy(button, operation, form=null) {
  if (button) { button.disabled=true; button.setAttribute('aria-busy','true'); }
  try { await operation(); } catch(error) { if(form) showError(form,error); else toast(error.message,true); }
  finally { if(button?.isConnected) {button.disabled=false;button.removeAttribute('aria-busy');} }
}
async function refresh() { state.user = await api('session'); if(state.user.authenticated || state.user.demo) state.data = await api('data'); else state.data=null; render(); }
function go(route) { location.hash=route; if(state.route===route) render(); }
function field(label, name, value='', {type='text', required=false, help='', full=false, autocomplete='', maxlength=2000}={}) {
  return `<div class="field${full?' full':''}"><label for="f-${name}">${label}${required?' <span class="sr-only">(obrigatório)</span>':''}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''} maxlength="${maxlength}" ${autocomplete?`autocomplete="${autocomplete}"`:''} ${help?`aria-describedby="help-${name}"`:''}>${help?`<div id="help-${name}" class="help">${help}</div>`:''}</div>`;
}
function textarea(label,name,value='',help='') { return `<div class="field"><label for="f-${name}">${label}</label><textarea id="f-${name}" name="${name}" maxlength="6000">${esc(value)}</textarea>${help?`<p class="help">${help}</p>`:''}</div>`; }
function auth() {
  const setup = !state.user.configured;
  document.title = `${setup?'Primeiro acesso':'Entrar'} · OrçaFlow`;
  app.innerHTML = `<div class="auth"><section class="auth-story"><a class="brand" href="#today">orçaflow</a><div><h1>Seu trabalho, bem acompanhado.</h1><p>Do primeiro contato à proposta aprovada. Um lugar para cuidar da parte comercial do seu negócio.</p></div><div class="auth-note">Seus dados ficam no computador do aplicativo.<br>Sem mensalidade. Sem conta em nuvem.</div></section><main id="main" class="auth-content"><div class="auth-box"><h2>${setup?'Prepare seu espaço de trabalho.':'Bom ter você de volta.'}</h2><p>${setup?'Configure seu acesso uma vez. Depois, é só entrar e continuar de onde parou.':'Entre com a senha deste espaço de trabalho.'}</p><form data-form="${setup?'setup':'login'}">${setup?field('Como podemos chamar você?','name','',{required:true,autocomplete:'name',maxlength:100})+field('Nome do seu negócio','company','',{help:'Esse nome aparece no cabeçalho das propostas.',maxlength:150}):''}<div class="field"><div class="password-row"><label for="f-password">${setup?'Crie uma senha':'Sua senha'}</label><button class="text-link" type="button" data-action="show-password">Mostrar senha</button></div><input id="f-password" name="password" type="password" required ${setup?'minlength="10"':''} maxlength="200" autocomplete="${setup?'new-password':'current-password'}" ${setup?'aria-describedby="password-help"':''}>${setup?'<div class="help" id="password-help">Use pelo menos 10 caracteres. Guarde a senha em um lugar seguro.</div>':''}</div>${errorBox()}<button class="btn primary" type="submit">${setup?'Começar a usar':'Entrar no meu espaço'} ${icon('arrow')}</button></form><div class="auth-demo"><p>Quer conhecer antes de começar?</p><button type="button" class="text-link" data-action="demo">Experimentar com dados de exemplo</button></div></div></main></div>`;
}
function shell(content, section='today') {
  const business = state.data.settings.company || state.user.name || 'Meu negócio';
  return `<header class="topbar"><div class="top-inner"><a class="brand" href="#today" aria-label="OrçaFlow, início">orçaflow</a><nav class="nav" aria-label="Navegação principal">${[['today','Hoje'],['quotes','Orçamentos'],['customers','Clientes'],['tasks','Agenda']].map(([id,label])=>`<a href="#${id}" ${section===id?'aria-current="page"':''}>${label}</a>`).join('')}</nav><div class="top-actions"><a class="btn quiet account" href="#settings">${esc(business)}</a><button class="btn quiet icon-btn" data-action="help" aria-label="Ajuda">${icon('help')}</button><a class="btn primary" href="#quote/new">${icon('plus')} Novo orçamento</a></div></div></header>${state.user.demo?'<div class="demo-band"><span>Você está experimentando com dados de exemplo.</span><button class="text-link" data-action="exit-demo">Voltar aos meus dados</button></div>':''}<main id="main" class="workspace" tabindex="-1">${content}</main><footer class="footer"><span>OrçaFlow · ${esc(state.user.version)}</span><span>Seus dados são salvos neste computador.</span><span><a href="#settings">Meu negócio e backups</a>${state.user.authenticated?` · <button class="text-link" data-action="logout">Sair</button>`:''}</span></footer>`;
}
function pageHead(title, subtitle='', actions='') { return `<div class="page-head"><div><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div>${actions?`<div class="heading-actions">${actions}</div>`:''}</div>`; }
function taskRows(tasks) {
  return `<ul class="task-list">${tasks.map(t=>`<li class="task-item${t.due<today()?' overdue':''}"><input type="checkbox" data-action="complete-task" data-id="${t.id}" aria-label="Concluir: ${esc(t.title)}"><time class="task-date" datetime="${esc(t.due)}">${t.due===today()?'Hoje':date(t.due)}${t.due<today()?'<br>Atrasado':''}</time><div><div class="task-title">${esc(t.title)}</div><div class="task-subtitle">${t.quote_id?`<a href="#quote/${t.quote_id}">${esc(t.quote_title)}</a>`:'Tarefa do seu negócio'}${t.automatic?' · retorno agendado':''}</div></div></li>`).join('')}</ul>`;
}
function todayPage() {
  const d=state.data, s=d.dashboard, first=!d.customers.length, upcoming=d.tasks.slice(0,6);
  const dateText = new Intl.DateTimeFormat('pt-BR',{day:'numeric',month:'long'}).format(new Date());
  let content=pageHead(`Hoje, ${dateText}.`,d.tasks.length?`${d.tasks.length} ${d.tasks.length===1?'próximo passo para acompanhar.':'próximos passos para acompanhar.'}`:'Um bom dia para dar andamento às suas propostas.',b(`${icon('plus')} Nova tarefa`,'new-task'));
  if(first) content+=`<section class="getting-started"><div><h2>Seu primeiro orçamento começa pelo cliente.</h2><p>Cadastre com quem você vai trabalhar. Depois, descreva o serviço e prepare a proposta.</p>${b('Cadastrar meu primeiro cliente '+icon('arrow'),'new-customer','',true)}</div><ol class="steps"><li><div><strong>Configure seu negócio</strong><p>Nome e contato no cabeçalho das propostas.</p><a href="#settings">Conferir meus dados</a></div></li><li><div><strong>Cadastre um cliente</strong><p>Só o nome é obrigatório. Complete o resto quando quiser.</p></div></li><li><div><strong>Prepare o orçamento</strong><p>Adicione os serviços, confira o valor e exporte a proposta.</p></div></li></ol></section>`;
  content+=`<div class="day-grid"><div><section><div class="section-head"><h2>Próximos contatos</h2><a class="text-link small" href="#tasks">Ver agenda</a></div>${upcoming.length?taskRows(upcoming):'<div class="empty-inline"><p>Nenhum retorno pendente.</p><p>Ao marcar uma proposta como enviada, o OrçaFlow agenda o próximo contato para você.</p></div>'}</section><section class="section-gap"><div class="section-head"><h2>Orçamentos recentes</h2><a class="text-link small" href="#quotes">Ver todos</a></div>${d.quotes.length?`<div class="recent-list">${d.quotes.slice(0,4).map(q=>`<a class="recent-row" href="#quote/${q.id}"><div><strong>${esc(q.title)}</strong><span class="muted">${esc(q.customer.name)}</span></div>${badge(q.stage)}<span class="money">${money(q.total)}</span></a>`).join('')}</div>`:'<div class="empty-inline">Seus orçamentos vão aparecer aqui, com o cliente, o valor e a etapa de cada proposta.</div>'}</section></div><aside class="overview"><h2>Seu negócio em resumo</h2><dl class="totals"><div><dt>Em negociação</dt><dd class="money">${money(s.pipeline)}</dd><div class="mini">Propostas enviadas e em conversa</div></div><div><dt>Orçamentos aprovados</dt><dd class="money">${money(s.approved)}</dd><div class="mini">Não representa pagamentos recebidos</div></div></dl><ul class="stage-list">${stages.slice(0,4).map((stage,i)=>`<li><span><span class="stage-dot ${i===3?'won':i>0?'sent':''}"></span>${stage}</span><span class="number">${s.stages[stage]}</span></li>`).join('')}</ul>${s.expired?`<p class="small muted">${s.expired} proposta(s) com validade vencida. Confira antes de seguir.</p>`:''}</aside></div>`;
  return content;
}
function searchInput(key, label, placeholder) { return `<div class="search">${icon('search')}<label class="sr-only" for="search-${key}">${label}</label><input id="search-${key}" type="search" data-search="${key}" value="${esc(state.filters[key])}" placeholder="${placeholder}" autocomplete="off"></div>`; }
function customersPage() { return pageHead('Clientes','As pessoas e empresas com quem você trabalha.',b('Importar lista','import-customers')+b(`${icon('plus')} Novo cliente`,'new-customer','',true))+`<div class="toolbar">${searchInput('customers','Buscar clientes','Buscar por nome, empresa ou contato')}<span class="count" id="record-count"></span></div><div id="record-content"></div>`; }
function quotesPage() { return pageHead('Orçamentos','Acompanhe cada proposta, do rascunho à aprovação.',`<a class="btn primary" href="#quote/new">${icon('plus')} Novo orçamento</a>`)+`<div class="toolbar">${searchInput('quotes','Buscar orçamentos','Buscar proposta ou cliente')}<label class="sr-only" for="filter-stage">Etapa dos orçamentos</label><select class="filter-select" id="filter-stage" data-filter="stage">${['Todos',...stages].map(s=>`<option ${s===state.filters.stage?'selected':''}>${s}</option>`).join('')}</select><span class="count" id="record-count"></span></div><div id="record-content"></div>`; }
function records() {
  const target=document.querySelector('#record-content'); if(!target)return;
  const customer=state.route==='customers', key=customer?'customers':'quotes', query=state.filters[key].toLocaleLowerCase('pt-BR');
  const all=state.data[key];
  const rows=all.filter(x=>(customer?`${x.name} ${x.company} ${x.email} ${x.phone}`:`${x.number} ${x.title} ${x.customer.name}`).toLocaleLowerCase('pt-BR').includes(query)).filter(q=>customer||state.filters.stage==='Todos'||q.stage===state.filters.stage);
  document.querySelector('#record-count').textContent=`${rows.length} ${customer?'cliente(s)':'orçamento(s)'}`;
  if(!rows.length) { target.innerHTML=all.length?empty('Nenhum resultado por aqui.','Tente outro nome ou ajuste o filtro.'):customer?empty('Quem será seu primeiro cliente?','Cadastre o nome agora e complete os contatos quando precisar.',b('Cadastrar cliente','new-customer','',true)):empty('Vamos preparar sua primeira proposta?','Escolha um cliente, adicione seus serviços e confira o orçamento.',`<a class="btn primary" href="#quote/new">Criar orçamento</a>`);return; }
  target.innerHTML=customer?`<div class="table-wrap"><table class="record-table"><thead><tr><th>Cliente</th><th>E-mail</th><th>Telefone</th><th></th></tr></thead><tbody>${rows.map(c=>`<tr><td><strong>${esc(c.name)}</strong><div class="muted">${esc(c.company||'Pessoa física')}</div></td><td data-label="E-mail">${esc(c.email||'Não informado')}</td><td data-label="Telefone">${esc(c.phone||'Não informado')}</td><td class="actions">${b('Editar','edit-customer',c.id)}</td></tr>`).join('')}</tbody></table></div>`:`<div class="table-wrap"><table class="record-table"><thead><tr><th>Proposta / cliente</th><th>Etapa</th><th>Validade</th><th class="align-right">Valor</th><th></th></tr></thead><tbody>${rows.map(q=>`<tr><td><a class="table-title" href="#quote/${q.id}"><strong>${esc(q.title)}</strong></a><div class="muted">${esc(q.customer.name)} · ${esc(q.number)}</div></td><td data-label="Etapa">${badge(q.stage)}</td><td data-label="Validade" ${q.expired?'class="success"':''}>${fullDate(q.expires)}${q.expired?'<div class="muted">Vencida</div>':''}</td><td data-label="Valor" class="money align-right">${money(q.total)}</td><td class="actions"><a class="btn quiet" href="#quote/${q.id}">Abrir ${icon('arrow')}</a></td></tr>`).join('')}</tbody></table></div>`;
}
function tasksPage() { return pageHead('Agenda','Uma lista clara do que fazer a seguir.',b(`${icon('plus')} Nova tarefa`,'new-task','',true))+(state.data.tasks.length?taskRows(state.data.tasks):empty('Tudo em dia.','Seus retornos aparecem aqui quando uma proposta é enviada. Você também pode criar uma tarefa.',b('Criar tarefa','new-task')))+`<p class="small muted section-gap">Enviado agenda um retorno para daqui a 3 dias; Negociação, para daqui a 2 dias. Nenhuma mensagem é enviada automaticamente.</p>`; }
function newDraft(id=null) {
  const q=id?state.data.quotes.find(q=>q.id===Number(id)):null;
  state.draft={quote_id:q?.id,expected_updated:q?.updated,customer_id:q?.customer_id || state.data.customers[0]?.id || '',title:q?.title || '',expires:q?.expires || afterDays(15),discount:q?String(q.discount_cents/100):'0,00',notes:q?.notes || '',items:q?q.items.map(i=>({description:i.description,quantity:String(i.qty_milli/1000),unit_price:String(i.unit_cents/100)})):[{description:'',quantity:'1',unit_price:''}]};
  state.dirty=false;
}
function editorPage(id=null) {
  if(!state.data.customers.length) return pageHead('Novo orçamento')+empty('Primeiro, vamos conhecer o cliente.','Só precisamos do nome para começar. Você volta ao orçamento em seguida.',b('Cadastrar cliente','new-customer','',true));
  if(!state.draft || state.draft.quote_id!== (id?Number(id):undefined))newDraft(id);
  const d=state.draft;
  return `<a class="back" href="#quotes">${icon('back')} Voltar aos orçamentos</a>${pageHead(id?'Editar rascunho':'Novo orçamento','Defina o escopo, confira os valores e prepare a proposta.')}<form data-form="quote"><div class="editor-grid"><div><section class="editor-section"><h2>Sobre a proposta</h2><div class="form-grid"><div class="field"><label for="quote-customer">Cliente</label><select id="quote-customer" name="customer_id" data-draft="customer_id" required>${state.data.customers.map(c=>`<option value="${c.id}" ${Number(d.customer_id)===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</select></div><div class="field"><label for="quote-expires">Válida até</label><input id="quote-expires" type="date" data-draft="expires" name="expires" value="${esc(d.expires)}" required></div><div class="field full"><label for="quote-title">Nome do projeto ou serviço</label><input id="quote-title" name="title" data-draft="title" value="${esc(d.title)}" placeholder="Ex.: Identidade visual para a loja" maxlength="200" required></div></div></section><section class="editor-section"><h2>O que está incluído?</h2><div class="line-head" aria-hidden="true"><span>Serviço ou produto</span><span>Qtd.</span><span>Valor unitário</span><span class="align-right">Subtotal</span><span></span></div><div id="quote-lines"></div><div class="line-tools">${b(`${icon('plus')} Adicionar item`,'add-line')}</div></section><section class="editor-section"><h2>Combine os detalhes</h2><div class="field"><label for="quote-notes">Prazo, pagamento e observações</label><textarea id="quote-notes" name="notes" data-draft="notes" maxlength="6000" placeholder="Descreva o prazo de entrega, a forma de pagamento e o que o cliente precisa saber.">${esc(d.notes)}</textarea><div class="help">Esse texto aparece na proposta entregue ao cliente.</div></div></section></div><aside class="summary"><h2>Resumo do orçamento</h2><dl><div><dt>Itens</dt><dd id="summary-subtotal" class="money">R$ 0,00</dd></div></dl><div class="field"><label for="quote-discount">Desconto em reais</label><input id="quote-discount" name="discount" data-draft="discount" value="${esc(d.discount)}" inputmode="decimal" required></div><dl><div class="total-line"><dt>Total</dt><dd id="summary-total" class="money">R$ 0,00</dd></div></dl>${errorBox()}<button class="btn primary" type="submit">Salvar rascunho ${icon('check')}</button><a class="btn quiet" href="#quotes">Cancelar</a><p class="small muted">Você confere e exporta a proposta depois de salvar. O cliente ainda não recebe nada.</p></aside></div></form>`;
}
function lineRows() {
  const target=document.querySelector('#quote-lines'); if(!target)return;
  target.innerHTML=state.draft.items.map((i,index)=>`<div class="line-row"><div class="field line-description" data-label="Serviço ou produto"><textarea aria-label="Descrição do item ${index+1}" data-line="${index}" data-key="description" maxlength="500" required>${esc(i.description)}</textarea></div><div class="field" data-label="Quantidade"><input aria-label="Quantidade do item ${index+1}" data-line="${index}" data-key="quantity" value="${esc(i.quantity)}" inputmode="decimal" required></div><div class="field" data-label="Valor unitário em reais"><input aria-label="Valor unitário do item ${index+1}" data-line="${index}" data-key="unit_price" value="${esc(i.unit_price)}" inputmode="decimal" placeholder="0,00" required></div><span class="money" data-line-total="${index}">R$ 0,00</span><button type="button" class="btn icon-btn danger" data-action="remove-line" data-id="${index}" aria-label="Remover item ${index+1}" ${state.draft.items.length===1?'disabled':''}>${icon('trash')}</button></div>`).join('');
  summary();
}
function scaled(raw, places) {
  let s=String(raw).trim().replaceAll(' ',''); if(s.includes(','))s=s.replaceAll('.','').replace(',','.');
  if(!/^\d+(\.\d*)?$/.test(s))return null; const [whole, fraction='']=s.split('.');
  if(fraction.length>places && /[1-9]/.test(fraction.slice(places)))return null;
  return BigInt(whole)*10n**BigInt(places)+BigInt(fraction.slice(0,places).padEnd(places,'0') || '0');
}
function bigMoney(value) { if(value===null)return 'Confira o valor';return `${value<0n?'-':''}R$ ${(value<0n?-value:value)/100n}`.replace(/\d+$/,s=>BigInt(s).toLocaleString('pt-BR'))+','+String((value<0n?-value:value)%100n).padStart(2,'0'); }
function summary() {
  if(!state.draft)return;let subtotal=0n,valid=true;
  state.draft.items.forEach((i,index)=>{const q=scaled(i.quantity,3),p=scaled(i.unit_price,2);const t=q===null||p===null?null:(q*p+500n)/1000n; if(t===null)valid=false;else subtotal+=t; const element=document.querySelector(`[data-line-total="${index}"]`);if(element)element.textContent=bigMoney(t);});
  const discount=scaled(state.draft.discount,2);
  const sub=document.querySelector('#summary-subtotal'),total=document.querySelector('#summary-total');
  if(sub)sub.textContent=valid?bigMoney(subtotal):'Confira os itens';
  if(total)total.textContent=valid&&discount!==null?bigMoney(subtotal-discount):'Confira os valores';
}
function quotePage(id) {
  const q=state.data.quotes.find(q=>q.id===Number(id));if(!q)return empty('Orçamento não encontrado.','Volte à lista para escolher uma proposta.',`<a class="btn" href="#quotes">Ver orçamentos</a>`);
  return `<a class="back" href="#quotes">${icon('back')} Voltar aos orçamentos</a>${pageHead(esc(q.title),`${esc(q.number)} · ${esc(q.customer.name)}`,q.stage==='Rascunho'?`<a class="btn" href="#edit/${q.id}">Editar rascunho</a>`:b('Duplicar proposta','duplicate',q.id))}<div class="detail-layout"><article><div class="quote-heading"><h2>${esc(q.customer.name)}</h2><p class="muted">${[q.customer.company,q.customer.email,q.customer.phone].filter(Boolean).map(esc).join('<br>') || 'Contatos não informados.'}</p><span class="small muted">Validade: ${fullDate(q.expires)}${q.expired?' · confira a data antes de enviar':''}</span></div><h2>Itens da proposta</h2><div class="table-wrap"><table class="detail-items"><thead><tr><th>Descrição</th><th>Qtd.</th><th class="align-right">Unitário</th><th class="align-right">Subtotal</th></tr></thead><tbody>${q.items.map(i=>`<tr><td>${esc(i.description)}</td><td>${i.qty_milli/1000}</td><td class="money align-right">${money(i.unit_cents)}</td><td class="money align-right">${money(Math.floor((i.qty_milli*i.unit_cents+500)/1000))}</td></tr>`).join('')}</tbody></table></div>${q.discount_cents?`<p class="small muted align-right">Desconto: ${money(q.discount_cents)}</p>`:''}<p class="detail-total money">Total ${money(q.total)}</p><h2 class="section-gap">Condições e escopo</h2><p class="quote-conditions">${esc(q.notes || 'Condições a combinar com o cliente.')}</p></article><aside class="detail-aside"><h2>Acompanhar proposta</h2>${badge(q.stage)}<div class="field section-gap"><label for="quote-stage">Atualizar etapa</label><select id="quote-stage"><option value="">Escolha a próxima etapa</option>${stages.filter(s=>s!=='Rascunho'&&s!==q.stage).map(s=>`<option>${s}</option>`).join('')}</select><div class="help">Marque como enviada depois de enviar ao cliente. O próximo contato é agendado na sua agenda.</div></div>${b('Salvar etapa','save-stage',q.id,true)}<a class="btn" href="/api/quotes/${q.id}/proposal" download>${icon('down')} Baixar proposta</a>${b('Copiar texto de retorno','copy-message',q.id)}<p class="small muted">Abra a proposta baixada para imprimir ou salvar como PDF no navegador.</p><h3 class="section-gap">Histórico</h3><ul class="timeline">${q.events.map(e=>`<li><time>${new Date(e.created).toLocaleString('pt-BR',{dateStyle:'short',timeStyle:'short'})}</time>${esc(e.description)}</li>`).join('')}</ul></aside></div>`;
}
function settingsPage() {
  const s=state.data.settings;
  return pageHead('Meu negócio','Seus dados nas propostas. Seus arquivos sob seu controle.')+`<div class="settings-grid"><form class="form-panel" data-form="settings"><h2>Cabeçalho das propostas</h2>${field('Nome do negócio','company',s.company,{maxlength:150})}${field('E-mail de contato','email',s.email,{type:'email',maxlength:254})}${field('Telefone','phone',s.phone,{type:'tel',maxlength:60})}${textarea('Rodapé da proposta','footer',s.footer,'Ex.: horário de atendimento ou uma observação para seus clientes.')}${errorBox()}<button type="submit" class="btn primary">Salvar meus dados</button></form><div><section><h2>Uma cópia para ficar tranquilo.</h2><p class="muted small">Baixe um backup regularmente e guarde uma cópia em outro lugar. Ele contém seus clientes, orçamentos e tarefas.</p><div class="settings-actions"><a class="btn primary" href="/api/export/backup" download>${icon('down')} Baixar backup</a>${b('Restaurar backup','restore-backup')}</div><p class="small muted">Ao restaurar, o OrçaFlow preserva uma cópia da base anterior neste computador. Sua senha de acesso continua a mesma.</p></section><hr class="divider"><section><h2>Levar os dados para uma planilha</h2><p class="small muted">Exporte a relação dos orçamentos em CSV. Os valores ficam em centavos para preservar a precisão.</p><a class="btn" href="/api/export/quotes" download>Exportar orçamentos</a></section>${!state.user.demo?`<hr class="divider"><section><h2>Seu acesso</h2><p class="small muted">Este espaço é protegido por senha. Se mudar a senha, outros navegadores precisam entrar novamente.</p>${b('Alterar minha senha','password')}</section>`:''}</div></div>`;
}
function render() {
  if(!state.user)return;
  if(!state.user.authenticated&&!state.user.demo){auth();return;}
  const route=(location.hash.slice(1)||'today').split('?')[0];state.route=route;
  let content, section=route.split('/')[0];
  if(route==='today')content=todayPage();else if(route==='customers')content=customersPage();else if(route==='quotes')content=quotesPage();else if(route==='tasks')content=tasksPage();else if(route==='settings')content=settingsPage();else if(route==='quote/new'){content=editorPage();section='quotes';}else if(route.startsWith('edit/')){const q=state.data.quotes.find(q=>q.id===Number(route.split('/')[1]));content=q?.stage==='Rascunho'?editorPage(q.id):quotePage(q?.id);section='quotes';}else if(route.startsWith('quote/')){content=quotePage(route.split('/')[1]);section='quotes';}else content=todayPage();
  app.innerHTML=shell(content,section);records();lineRows();
  if(route==='settings'&&state.data.recovery_available)document.querySelector('[href="/api/export/backup"]').insertAdjacentHTML('afterend','<a class="btn" href="/api/export/recovery" download>Baixar cópia anterior</a>');
  document.title=`${document.querySelector('h1')?.textContent || 'Hoje'} · OrçaFlow`;
}
function modal(title,content) {
  dialog.innerHTML=`<div class="dialog-body"><div class="dialog-head"><h2 id="dialog-title">${title}</h2><button class="btn quiet icon-btn" data-action="close-dialog" aria-label="Fechar">${icon('close')}</button></div>${content}</div>`;dialog.showModal();
}
function customerForm(id=null) {
  const c=state.data.customers.find(c=>c.id===Number(id)) || {};
  modal(id?'Editar cliente':'Novo cliente',`<p class="small muted">Só o nome é obrigatório. Os contatos podem ficar para depois.</p><form data-form="customer" data-id="${id || ''}">${field('Nome do cliente','name',c.name,{required:true,maxlength:150})}${field('Empresa (opcional)','company',c.company,{maxlength:150})}<div class="form-grid">${field('E-mail','email',c.email,{type:'email',maxlength:254})}${field('Telefone','phone',c.phone,{type:'tel',maxlength:60})}</div>${textarea('Anotações internas','notes',c.notes,'Essas anotações não aparecem nas propostas.')}${errorBox()}<div class="dialog-actions">${b('Cancelar','close-dialog')}<button class="btn primary" type="submit">Salvar cliente</button></div></form>`);
}
function fileForm(type) {
  const restore=type==='backup';
  modal(restore?'Restaurar seus dados':'Importar lista de clientes',`<p class="muted small">${restore?'Os dados atuais serão substituídos pelos do arquivo escolhido. Uma cópia da base anterior será preservada.':'Use um CSV com as colunas nome, empresa, email, telefone e observacoes. E-mails já cadastrados são ignorados.'}</p>${!restore?'<p class="small">Somente a coluna <strong>nome</strong> é obrigatória.</p>':''}<form data-form="${restore?'restore':'import-customers'}"><div class="field"><label for="import-file">${restore?'Backup do OrçaFlow':'Arquivo CSV'}</label><input id="import-file" type="file" name="file" accept="${restore?'.sqlite3':'.csv'}" required><div class="help">Limite de 12 MB.</div></div>${restore?'<div class="field"><label><input type="checkbox" name="confirm" required> Entendo que os dados atuais serão substituídos.</label></div>':''}${errorBox()}<div class="dialog-actions">${b('Cancelar','close-dialog')}<button class="btn primary" type="submit">${restore?'Restaurar dados':'Importar clientes'}</button></div></form>`);
}

document.addEventListener('submit',event=>{
  const form=event.target.closest('[data-form]');if(!form)return;event.preventDefault();const kind=form.dataset.form,values=Object.fromEntries(new FormData(form));
  busy(form.querySelector('[type=submit]'),async()=>{
    if(kind==='setup'||kind==='login') {await api(kind,{method:'POST',data:values});if(kind==='setup'&&values.company)await api('settings',{method:'POST',data:{company:values.company}});await refresh();go('today');return;}
    if(kind==='customer'){const result=await api('customers',{method:'POST',data:{...values,...(form.dataset.id?{customer_id:Number(form.dataset.id)}:{})}});dialog.close();await refresh();toast('Cliente salvo.');if(state.route==='quote/new'){state.draft=null;render();document.querySelector('#quote-customer').value=result.id;state.draft.customer_id=result.id;}return;}
    if(kind==='quote'){const result=await api('quotes',{method:'POST',data:{...state.draft,customer_id:Number(state.draft.customer_id)}});state.dirty=false;state.draft=null;await refresh();go(`quote/${result.id}`);toast('Rascunho salvo. Confira a proposta antes de enviar.');return;}
    if(kind==='settings'){await api('settings',{method:'POST',data:values});await refresh();toast('Dados do negócio salvos.');return;}
    if(kind==='task'){await api('tasks',{method:'POST',data:values});dialog.close();await refresh();toast('Tarefa adicionada à agenda.');return;}
    if(kind==='password'){await api('password',{method:'POST',data:values});dialog.close();await refresh();toast('Senha alterada. Outros acessos precisam entrar novamente.');return;}
    if(kind==='import-customers'||kind==='restore'){const result=await api(kind==='restore'?'import/backup':'import/customers',{method:'POST',form:new FormData(form)});dialog.close();await refresh();toast(kind==='restore'?'Dados restaurados. Uma cópia dos dados anteriores foi preservada neste computador.':`${result.added} cliente(s) importado(s). ${result.skipped} e-mail(s) já existente(s) ignorado(s).`);}
  },form);
});
document.addEventListener('click',event=>{
  const target=event.target.closest('[data-action]');if(!target)return;const action=target.dataset.action,id=target.dataset.id;
  if(action==='close-dialog'){dialog.close();return;}
  if(action==='show-password'){const input=document.querySelector('#f-password');input.type=input.type==='password'?'text':'password';target.textContent=input.type==='password'?'Mostrar senha':'Ocultar senha';return;}
  if(action==='new-customer'||action==='edit-customer'){customerForm(action==='edit-customer'?id:null);return;}
  if(action==='new-task'){modal('O que precisa ser feito?',`<form data-form="task">${field('Tarefa','title','',{required:true,maxlength:250})}${field('Data','due',today(),{type:'date',required:true})}${errorBox()}<div class="dialog-actions">${b('Cancelar','close-dialog')}<button class="btn primary" type="submit">Adicionar à agenda</button></div></form>`);return;}
  if(action==='add-line'){state.draft.items.push({description:'',quantity:'1',unit_price:''});state.dirty=true;lineRows();document.querySelector(`[data-line="${state.draft.items.length-1}"]`).focus();return;}
  if(action==='remove-line'){state.draft.items.splice(Number(id),1);state.dirty=true;lineRows();return;}
  if(action==='import-customers'){fileForm('customers');return;}
  if(action==='restore-backup'){fileForm('backup');return;}
  if(action==='password'){modal('Alterar sua senha',`<form data-form="password">${field('Senha atual','current','',{type:'password',required:true,autocomplete:'current-password'})}${field('Nova senha','password','',{type:'password',required:true,help:'Use pelo menos 10 caracteres.',autocomplete:'new-password'})}${errorBox()}<div class="dialog-actions">${b('Cancelar','close-dialog')}<button class="btn primary" type="submit">Salvar nova senha</button></div></form>`);return;}
  if(action==='help'){modal('Um passo de cada vez.',`<ol><li>Em <strong>Meu negócio</strong>, configure o cabeçalho da proposta.</li><li>Cadastre o cliente. O nome é suficiente para começar.</li><li>Crie o orçamento e adicione os serviços.</li><li>Salve, confira e baixe a proposta para enviar.</li><li>Depois de enviar, atualize a etapa para <strong>Enviado</strong>.</li><li>Acompanhe o retorno na <strong>Agenda</strong>.</li></ol><p class="small muted">Para salvar a proposta como PDF, abra o arquivo baixado e use Imprimir no navegador. Faça backups regularmente em Meu negócio.</p><div class="dialog-actions">${b('Entendi','close-dialog','',true)}</div>`);return;}
  busy(target,async()=>{
    if(action==='demo'){await api('demo',{method:'POST',data:{}});await refresh();go('today');}
    if(action==='exit-demo'){await api('demo/exit',{method:'POST',data:{}});state.draft=null;state.dirty=false;await refresh();go('today');}
    if(action==='logout'){await api('logout',{method:'POST',data:{}});state.draft=null;state.dirty=false;await refresh();}
    if(action==='complete-task'){try{await api(`tasks/${id}/complete`,{method:'POST',data:{}});await refresh();toast('Tarefa concluída.');}catch(error){target.checked=false;throw error;}}
    if(action==='save-stage'){const stage=document.querySelector('#quote-stage').value;if(!stage)throw new Error('Escolha a etapa antes de salvar.');await api(`quotes/${id}/stage`,{method:'POST',data:{stage}});await refresh();toast('Etapa atualizada. Confira os próximos contatos na agenda.');}
    if(action==='duplicate'){const result=await api(`quotes/${id}/duplicate`,{method:'POST',data:{}});await refresh();state.draft=null;go(`edit/${result.id}`);toast('Uma cópia editável foi criada.');}
    if(action==='copy-message'){const result=await api(`quotes/${id}/message`);try{await navigator.clipboard.writeText(result.message);toast('Texto copiado. Revise antes de enviar ao cliente.');}catch{modal('Seu texto de retorno',`<p class="small muted">Selecione e copie o texto abaixo para revisar e enviar.</p><textarea readonly aria-label="Texto de retorno">${esc(result.message)}</textarea><div class="dialog-actions">${b('Fechar','close-dialog')}</div>`);}}
  });
});
document.addEventListener('input',event=>{
  const input=event.target;
  if(input.dataset.search){state.filters[input.dataset.search]=input.value;records();}
  if(input.dataset.draft){state.draft[input.dataset.draft]=input.value;state.dirty=true;summary();}
  if(input.dataset.line!==undefined){state.draft.items[Number(input.dataset.line)][input.dataset.key]=input.value;state.dirty=true;summary();}
});
document.addEventListener('change',event=>{if(event.target.dataset.filter){state.filters.stage=event.target.value;records();}});
let reverting=false;
window.addEventListener('hashchange',()=>{
  if(reverting){reverting=false;return;}
  if(state.dirty&&!window.confirm('Seu rascunho ainda não foi salvo. Sair sem salvar?')){reverting=true;location.hash=state.route;return;}
  state.dirty=false;state.draft=null;render();document.querySelector('#main')?.focus({preventScroll:true});window.scrollTo(0,0);
});
window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
async function start(){try{state.user=await api('session');if(new URLSearchParams(location.search).get('demo')==='1'){await api('demo',{method:'POST',data:{}});history.replaceState(null,'',location.pathname+location.hash);}await refresh();}catch(error){app.innerHTML=`<main id="main" class="initial"><h1>Não foi possível abrir seu espaço.</h1><p>${esc(error.message)}</p><button class="btn primary" data-action="reload">Tentar novamente</button></main>`;document.querySelector('[data-action="reload"]').addEventListener('click',()=>location.reload());}}
start();
