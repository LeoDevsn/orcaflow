// Integração do front em DOM simulado + API HTTP real. Não substitui revisão visual.
import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM, VirtualConsole} from 'jsdom';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';
import {setTimeout as pause} from 'node:timers/promises';

const root=new URL('../',import.meta.url);
const html=await readFile(new URL('../orca_flow/frontend/index.html',import.meta.url),'utf8');
const script=await readFile(new URL('../orca_flow/frontend/app.js',import.meta.url),'utf8');
async function waitFor(condition,label){for(let i=0;i<200;i++){if(condition())return;await pause(25);}throw new Error(`Não concluiu: ${label}`);}

test('Fluxo completo: primeiro acesso, cliente, orçamento, erro recuperável, etapa e agenda',async t=>{
  const directory=await mkdtemp(join(tmpdir(),'orcaflow-ui-test-'));
  const probe=createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  const child=spawn('python',['-X','utf8','-m','orca_flow','--data-dir',directory,'--server','--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe'],windowsHide:true});
  let logs='';child.stdout.on('data',chunk=>logs+=chunk);child.stderr.on('data',chunk=>logs+=chunk);
  const base=`http://127.0.0.1:${port}`;
  let dom;
  t.after(async()=>{dom?.window.close();child.kill();await new Promise(resolve=>child.once('exit',resolve));await rm(directory,{recursive:true,force:true});});
  await waitFor(()=>logs.includes('OrçaFlow em'),'servidor pronto');
  const errors=[];const console=new VirtualConsole();console.on('jsdomError',e=>errors.push(e.message));
  dom=new JSDOM(html,{url:base,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:console});
  const w=dom.window;
  w.scrollTo=()=>{};w.confirm=()=>true;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=async(path,options={})=>{
    const url=new URL(path,base).href;const headers=new Headers(options.headers);const cookie=await dom.cookieJar.getCookieString(url);if(cookie)headers.set('Cookie',cookie);
    const response=await fetch(url,{...options,headers});for(const value of response.headers.getSetCookie())await dom.cookieJar.setCookie(value,url);return response;
  };
  // Usa FormData nativo do DOM para ler os formulários. Uploads são testados na API Python.
  w.eval(script);
  const doc=w.document;
  const fill=(selector,value)=>{const element=doc.querySelector(selector);assert.ok(element,selector);element.value=value;element.dispatchEvent(new w.Event('input',{bubbles:true}));};
  const submit=selector=>doc.querySelector(selector).dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
  const click=selector=>{assert.ok(doc.querySelector(selector),selector);doc.querySelector(selector).click();};
  await waitFor(()=>doc.querySelector('[data-form="setup"]'),'primeiro acesso');
  fill('[name="name"]','Pessoa de teste');fill('[name="company"]','Oficina de exemplo');fill('[name="password"]','senha-temporaria-123');submit('[data-form="setup"]');
  await waitFor(()=>doc.querySelector('[data-action="new-customer"]'),'área vazia orientada');
  assert.match(doc.body.textContent,/Seu primeiro orçamento começa pelo cliente/);
  click('[data-action="new-customer"]');fill('#dialog [name="name"]','Cliente <exemplo>');fill('#dialog [name="email"]','cliente@example.com');submit('[data-form="customer"]');
  await waitFor(()=>!doc.querySelector('#dialog').open,'cliente salvo');
  w.location.hash='quote/new';await waitFor(()=>doc.querySelector('#quote-title'),'editor de orçamento');
  fill('#quote-title','Consultoria de exemplo');fill('[data-key="description"]','Serviço de consultoria');fill('[data-key="quantity"]','1,5');fill('[data-key="unit_price"]','120,00');
  assert.match(doc.querySelector('#summary-total').textContent,/180,00/);
  fill('#quote-discount','999');submit('[data-form="quote"]');
  await waitFor(()=>doc.querySelector('[data-form="quote"] [data-error]')?.textContent.includes('desconto'),'erro do desconto');
  assert.equal(doc.querySelector('#quote-title').value,'Consultoria de exemplo');
  fill('#quote-discount','0');submit('[data-form="quote"]');
  await waitFor(()=>doc.querySelector('#quote-stage'),'orçamento salvo');
  assert.match(doc.body.textContent,/Cliente <exemplo>/);assert.equal(doc.querySelector('img'),null);
  doc.querySelector('#quote-stage').value='Enviado';click('[data-action="save-stage"]');
  await waitFor(()=>doc.querySelector('.detail-aside .badge')?.textContent==='Enviado','etapa salva');
  w.location.hash='tasks';await waitFor(()=>doc.querySelector('[data-action="complete-task"]'),'retorno agendado');
  assert.match(doc.body.textContent,/Retornar contato: Consultoria de exemplo/);
  click('[data-action="complete-task"]');await waitFor(()=>doc.body.textContent.includes('Tudo em dia.'),'tarefa concluída');
  w.location.hash='customers';await waitFor(()=>doc.querySelector('#search-customers'),'busca de clientes');
  fill('#search-customers','não existe');assert.match(doc.querySelector('#record-content').textContent,/Nenhum resultado/);
  fill('#search-customers','cliente');assert.match(doc.querySelector('#record-content').textContent,/Cliente <exemplo>/);
  assert.deepEqual(errors,[]);
});
