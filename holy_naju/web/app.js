// 기존 로컬 API로 실제 검색·자료실·기록과 버전별 원문/미검토 번역을 연결한다.
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceName = value => ({vatican:'교황청',naju:'나주',user_import:'가져온 파일'}[value] || value);
const time = value => value ? new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}) : '시각 미확인';
let screen='search', run=null, hits=[], selected=null, passage=null, translation=null, documents=[], records=[];
let viewTicket=0, readerTicket=0, translationTicket=0, searching=false, importing=false;

async function api(path, payload, upload=false) {
  const options=payload===undefined ? {} : {method:'POST',headers:{'Content-Type':upload?'application/octet-stream':'application/json','X-Holy-Naju':'1'},body:upload?payload:JSON.stringify(payload)};
  const response=await fetch(path, options);
  const data=await response.json();
  if(!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function status(id, text, error=false) { $(id).textContent=text; $(id).classList.toggle('error',error); }
function nav(next) {
  screen=next; viewTicket++; readerTicket++;
  for(const name of ['search','library','history']) $('screen-'+name).hidden=name!==next;
  document.querySelectorAll('[data-screen]').forEach(button=>{if(button.dataset.screen===next) button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  return viewTicket;
}
function highlight(text,ranges=[]) {
  const chars=Array.from(text);let offset=0,result='';
  for(const [start,end] of ranges){result+=esc(chars.slice(offset,start).join(''))+'<mark>'+esc(chars.slice(start,end).join(''))+'</mark>';offset=end;}
  return result+esc(chars.slice(offset).join(''));
}
function locatorText(value) {
  if(value.page) return `PDF ${value.page}쪽 · 원본 페이지와 대조하세요.`;
  if(value.block!==undefined) return `추출 블록 ${value.block} · 공식 문단 번호가 아닙니다.`;
  return '원문 내 추출 위치 · 상세 정보 확인.';
}
function formOptions() {
  const values=new FormData($('search-form')), method=values.get('method');
  const options={query:String(values.get('query')).trim(),mode:method==='phrase'?'phrase':'keyword',retrieval:method==='hybrid'?'hybrid':'keyword',limit:Number(values.get('limit'))};
  for(const name of ['source','language','document_type','issued_from','issued_to']) if(values.get(name)) options[name]=values.get(name);
  return options;
}
function fillForm(record, query=record.query_original) {
  const form=$('search-form'); form.elements.query.value=query;
  for(const key of ['source','language','document_type','issued_from','issued_to']) form.elements[key].value=record.filters[key] || '';
  form.elements.method.value=record.mode==='phrase'?'phrase':record.retrieval;
  form.elements.limit.value=record.result_limit;
}
function updateHash() {
  const params=new URLSearchParams();if(run)params.set('run',run.id);if(passage)params.set('passage',passage.passage_id || passage.id);if(translation?.id)params.set('translation',translation.id);
  history.replaceState(null,'','#'+params.toString());
}
function renderResults() {
  const scroll=$('results').scrollTop;
  $('results').innerHTML=hits.length?hits.map((hit,index)=>`<button class="result" data-hit="${index}" aria-pressed="${selected===hit.passage_id}"><span class="chip">${esc(sourceName(hit.source))}</span><small>${esc(hit.language)}</small><h3>${esc(hit.title)}</h3><p>${highlight(hit.excerpt,hit.highlight_ranges)}</p><small>${esc(hit.issued_on || '발표일 미확인')} · ${esc(locatorText(hit.locator))}</small></button>`).join(''):'<p class="muted">조건에 맞는 근거 문단이 없습니다.</p>';
}
async function performSearch(options) {
  if(searching)return;
  const ticket=nav('search');searching=true;$('search-button').disabled=true;
  status('search-status','보관 자료를 검색하고 있습니다. 첫 의미 검색은 모델 로딩·임베딩 생성 시간이 필요합니다.');
  try {
    const result=await api('/api/search',options);
    if(ticket!==viewTicket)return;
    run=result;hits=result.hits;selected=null;passage=null;translation=null;
    const fallback=result.diagnostics?`\n의미 검색 비가용으로 키워드 검색을 사용했습니다. ${result.diagnostics.reason}`:'';
    status('search-status',`${hits.length}개 근거 · ${result.retrieval==='hybrid'?'키워드 + 의미':'키워드/구절'} · ${result.reused?'저장 결과 재사용':'새 검색'}\n최초 검색 ${time(result.created_at)} · 현재 보관 자료 대상.${fallback}`,Boolean(result.diagnostics));
    renderResults();updateHash();
    if(hits.length)await openPassage(hits[0].passage_id);else $('reader').innerHTML='<h2>원문 대조</h2><p class="muted">검색은 정상 완료했지만 근거가 없습니다.</p>';
  } catch(error) {if(ticket===viewTicket)status('search-status',`검색에 실패했습니다. 결과 없음과 다릅니다. ${error.message}${hits.length?' 아래 문단은 직전 결과이며 이번 검색 결과가 아닙니다.':''}`,true);}
  finally{searching=false;$('search-button').disabled=false;}
  $('results').scrollTop=scroll;
}
function renderReader() {
  const hit=hits.find(item=>item.passage_id===selected), p=passage;
  const korean=['ko','kor'].includes(p.language.toLowerCase().split('-')[0]);
  const originalRanges=hit?.highlight_ranges.map(([a,b])=>[a+hit.excerpt_start,b+hit.excerpt_start]) || [];
  const url=hit?.canonical_url ?? p.canonical_url;
  let sourceLink='';try{const parsed=new URL(url);if(parsed.protocol==='https:'&&!parsed.username&&!parsed.password)sourceLink=`<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">출처 사이트 열기</a>`;}catch{}
  $('reader').innerHTML=`<div class="reader-head"><span class="chip">${esc(sourceName(hit?.source || p.source))}</span><span class="chip">보관 원문 버전</span>${p.ocr_review_status?'<span class="chip caution">OCR '+esc(p.ocr_review_status)+'</span>':''}<h2>${esc(hit?.title || p.title)}</h2><p class="muted">${esc(locatorText(p.locator))} ${p.extraction_status==='partial'?'부분 추출 · 미처리 페이지가 있습니다.':''}</p>${hit?'<small>문헌명·출처 링크는 검색 당시 정보를 우선 표시합니다.</small>':''}</div><div class="parallel"><section><h3>보관 원문 <span class="chip">${esc(p.language)}</span></h3><div class="original" lang="${esc(p.language)}">${highlight(p.text,originalRanges)}</div></section><section><h3>${korean?'한국어 원문 · 번역 불필요':'한국어 번역'}</h3>${korean?'<p class="muted">왼쪽은 한국어 원문입니다. OCR 자료는 보관 파일과 대조하세요.</p>':`<span class="chip caution">로컬 생성 · 미검토 · 공식 번역 아님</span><label>저장된 번역 이력<select id="translation-picker"><option value="">저장 번역 선택</option>${p.translations.map(t=>`<option value="${esc(t.id)}" ${translation?.id===t.id?'selected':''}>${t.status==='completed'?'생성 완료':'실패'} · ${esc(time(t.created_at))} · ${esc(t.prompt_revision)}</option>`).join('')}</select></label><div id="translation-text"></div><div class="actions"><button data-action="translate" class="primary">로컬 한국어 번역</button><button data-action="retranslate">새로 생성</button></div><p class="muted">저장 이력은 모델 없이 열 수 있습니다. 새 번역은 원문을 로컬 모델에만 전달합니다. 부정·주어·가톨릭 용어를 반드시 대조하세요.</p>`}</section></div><div id="reader-status" class="status" role="status"></div><div class="actions">${sourceLink}<a href="/api/assets/${encodeURIComponent(p.asset_id)}" download>보관 파일 다운로드</a><button data-action="copy">근거와 ID 복사</button></div><small>원본 HTML은 이 화면에서 실행하지 않습니다. PDF는 내려받아 위에 표시된 페이지를 확인하세요.</small><details class="metadata"><summary>원문·생성 버전 정보</summary><p>원문 ${esc(p.version_id)}\n문단 ${esc(p.id)}\n보관 시각 ${esc(time(p.version_created_at))}\n위치 ${esc(JSON.stringify(p.locator))}</p><p id="translation-metadata"></p></details>`;
  if(!korean)renderTranslation();
}
function renderTranslation() {
  if(!$('translation-text'))return;
  if(!translation){$('translation-text').innerHTML='<p class="muted">저장된 번역이 없거나 선택하지 않았습니다. 원문은 그대로 읽을 수 있습니다.</p>';$('translation-metadata').textContent='';return;}
  $('translation-text').innerHTML=translation.status==='completed'?`<div class="translated">${esc(translation.text)}</div>`:`<p class="warning">번역 실패. ${esc(translation.error)} 원문을 확인하고 필요하면 재시도하세요.</p>`;
  $('translation-metadata').textContent=`번역 ${translation.id}\n상태 ${translation.status} / ${translation.review_status}\n모델 ${translation.model_profile.name} / ${translation.model_profile.digest || '미확인'}\n프롬프트 ${translation.prompt_revision}\n생성 ${time(translation.created_at)}`;
}
async function openSavedTranslation(id,ticket=readerTicket) {
  const request=++translationTicket;
  translation=null;renderTranslation();if($('translation-text'))$('translation-text').textContent='저장 번역을 여는 중입니다.';updateHash();
  try {const value=await api('/api/translations/'+encodeURIComponent(id));if(ticket!==readerTicket||request!==translationTicket||value.passage_id!==selected)return;translation=value;renderTranslation();if($('translation-picker'))$('translation-picker').value=id;updateHash();}
  catch(error){if(ticket===readerTicket&&request===translationTicket){renderTranslation();status('reader-status',`번역 이력을 열지 못했습니다. ${error.message}`,true);}}
}
async function openPassage(id, translationId=null, reveal=false) {
  const ticket=++readerTicket;selected=id;passage=null;translation=null;renderResults();$('reader').innerHTML='<h2>원문을 여는 중입니다.</h2>';
  try {const value=await api('/api/passages/'+encodeURIComponent(id));if(ticket!==readerTicket||screen!=='search')return;passage=value;renderReader();updateHash();if(reveal){$('reader').tabIndex=-1;$('reader').focus({preventScroll:true});if(innerWidth<=760)$('reader').scrollIntoView({block:'start'});}const saved=translationId || value.translations[0]?.id;if(saved)await openSavedTranslation(saved,ticket);}
  catch(error){if(ticket===readerTicket)$('reader').textContent=`원문을 열지 못했습니다. ${error.message}`;}
}
async function translate(refresh) {
  if(!passage)return;const id=selected,ticket=readerTicket,request=++translationTicket;
  document.querySelectorAll('[data-action=translate],[data-action=retranslate]').forEach(button=>button.disabled=true);
  status('reader-status','로컬 모델이 한국어 번역을 생성하고 있습니다. 원문은 계속 읽을 수 있습니다.');
  try {const value=await api('/api/translate',{passage_id:id,refresh});if(ticket!==readerTicket||request!==translationTicket)return;translation=value;const updated=await api('/api/passages/'+encodeURIComponent(id));if(ticket!==readerTicket||request!==translationTicket)return;passage=updated;renderReader();status('reader-status',value.reused?'저장 번역을 재사용했습니다.':'새 번역을 보관했습니다. 생성 완료는 내용 검토 완료가 아닙니다.');updateHash();}
  catch(error){if(ticket===readerTicket){status('reader-status',`번역 실패. ${error.message} 원문은 계속 읽을 수 있습니다.`,true);}}
  finally{if(ticket===readerTicket)document.querySelectorAll('[data-action=translate],[data-action=retranslate]').forEach(button=>button.disabled=false);}
}
async function loadLibrary() {
  const ticket=viewTicket;status('library-status','보관 자료를 확인하고 있습니다.');
  try{const value=await api('/api/library');documents=value;$('library-count').textContent=`로컬 문헌판 ${value.length}건 · 전체 수집 미완료`;
    if(ticket!==viewTicket)return;
    $('documents').innerHTML=value.length?value.map((doc,index)=>`<section class="row"><div><span class="chip">${esc(sourceName(doc.source))}</span><h3>${esc(doc.title)}</h3><small>${esc(doc.language)} · ${doc.passages}문단 · ${doc.versions}버전</small></div><div><span class="chip ${doc.status==='partial'?'caution':''}">${doc.status==='partial'?'부분 추출 · 확인 필요':'추출 완료 · 내용 미검토'}</span><button data-document="${index}">문헌 열기</button></div></section>`).join(''):'<p>보관한 문헌이 없습니다. 파일을 가져오거나 CLI로 자료를 준비하세요.</p>';
    status('library-status',`${value.length}개 문헌판. 출처·보관 상태를 확인하세요.`);
  }catch(error){if(ticket===viewTicket)status('library-status',`자료실 오류. ${error.message}`,true);}
}
async function openVersion(index) {
  const doc=documents[index],ticket=viewTicket;status('library-status','문헌의 현재 보관 버전을 여는 중입니다.');
  try{const value=await api('/api/versions/'+encodeURIComponent(doc.current_version_id));if(ticket!==viewTicket)return;
    $('version-view').innerHTML=`<section class="panel"><h2>${esc(doc.title)}</h2><p class="muted">버전 ${esc(value.version.id)} · ${esc(value.version.status)} · ${value.passages.length}문단</p><p class="muted">${value.pages.length?`${value.pages.length}개 추출 페이지. OCR 미검토/실패 페이지는 원본과 대조하세요.`:'HTML/TXT/DOCX 추출 문단. 공식 문단 번호와 다를 수 있습니다.'}</p><div class="passages">${value.passages.map(p=>`<button data-passage="${esc(p.id)}">${p.ordinal}. ${esc(p.text.slice(0,100))}</button>`).join('')}</div></section>`;status('library-status','문단을 선택하면 보관 원문과 대응 번역을 엽니다.');$('version-view').scrollIntoView({behavior:'smooth',block:'start'});
  }catch(error){if(ticket===viewTicket)status('library-status',`문헌 열기 실패. ${error.message}`,true);}
}
async function loadHistory() {
  const ticket=viewTicket;status('history-status','최근 검색 기록을 여는 중입니다.');
  try{const value=await api('/api/history');if(ticket!==viewTicket)return;records=value;
    $('history').innerHTML=value.length?value.map((item,index)=>`<section class="row"><div><span class="chip">${item.reused?'재사용 요청':'검색 요청'}</span><h3>${esc(item.query_original)}</h3><small>${esc(time(item.accessed_at))} · 실제 ${esc(item.retrieval)} · 최초 ${esc(time(item.searched_at))}</small><p class="muted">조건 ${esc(JSON.stringify(item.filters))}</p></div><div class="actions"><button data-history="${index}">당시 결과 열기</button><button data-rerun="${index}">현재 보관 자료로 재검색</button></div></section>`).join(''):'<p>아직 검색 기록이 없습니다.</p>';status('history-status',`최근 ${value.length}개 요청을 표시합니다.`);
  }catch(error){if(ticket===viewTicket)status('history-status',`기록 오류. ${error.message}`,true);}
}
async function openRun(id, query=null, refresh=false, passageId=null, translationId=null) {
  const ticket=nav('search');status('search-status','당시 검색 결과를 여는 중입니다.');
  try{const value=await api('/api/runs/'+encodeURIComponent(id));if(ticket!==viewTicket)return;if(passageId&&!value.hits.some(hit=>hit.passage_id===passageId))throw new Error('검색 기록과 문단이 일치하지 않습니다.');fillForm(value,query || value.query_original);
    if(refresh){await performSearch({...formOptions(),refresh:true});return;}
    run=value;hits=value.hits;selected=null;passage=null;translation=null;renderResults();status('search-status',`당시 결과 ${hits.length}개 · 최초 검색 ${time(value.created_at)}\n색인 ${value.index_generation_id} · 당시 원문 버전. 모델 없이 기록을 열었습니다.`);updateHash();
    const pid=passageId || hits[0]?.passage_id;if(pid)await openPassage(pid,translationId);else $('reader').innerHTML='<h2>당시 검색 결과가 비어 있습니다.</h2>';
  }catch(error){if(ticket===viewTicket)status('search-status',`기록 열기 실패. ${error.message}`,true);}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.screen){nav(button.dataset.screen);if(screen==='library')await loadLibrary();if(screen==='history')await loadHistory();}
  else if(button.dataset.hit!==undefined)await openPassage(hits[Number(button.dataset.hit)].passage_id,null,true);
  else if(button.dataset.document!==undefined)await openVersion(Number(button.dataset.document));
  else if(button.dataset.passage){nav('search');run=null;hits=[];status('search-status','자료실에서 선택한 문단 · 검색 실행이 아닙니다.');await openPassage(button.dataset.passage,null,true);}
  else if(button.dataset.history!==undefined||button.dataset.rerun!==undefined){const item=records[Number(button.dataset.history ?? button.dataset.rerun)];await openRun(item.run_id,item.query_original,button.dataset.rerun!==undefined);}
  else if(button.dataset.action==='translate'||button.dataset.action==='retranslate')await translate(button.dataset.action==='retranslate');
  else if(button.dataset.action==='copy'&&passage){
    const hit=hits.find(item=>item.passage_id===selected);
    try{await navigator.clipboard.writeText(`${hit?.title || passage.title}\n${passage.text}\n\n원문 ${passage.version_id}\n문단 ${passage.id}\n위치 ${JSON.stringify(passage.locator)}\n출처 ${hit?.canonical_url ?? passage.canonical_url ?? sourceName(passage.source)}\n${translation?`번역 ${translation.id} · ${translation.review_status}`:''}\n${location.href}`);status('reader-status','원문·근거 ID·현재 링크를 복사했습니다.');}
    catch{status('reader-status','클립보드에 접근하지 못했습니다. 근거 버전 정보를 직접 복사하세요.',true);}
  }
});
$('search-form').addEventListener('submit',event=>{event.preventDefault();performSearch(formOptions());});
document.addEventListener('change',event=>{if(event.target.id==='translation-picker'){if(event.target.value)openSavedTranslation(event.target.value);else{translationTicket++;translation=null;renderTranslation();updateHash();}}});
$('import-form').addEventListener('submit',async event=>{
  event.preventDefault();if(importing)return;const form=event.target,file=form.elements.file.files[0];if(!file)return;
  if(file.size>50*1024*1024||file.size===0){status('library-status','파일은 0바이트 초과 50MiB 이하여야 합니다.',true);return;}
  importing=true;$('import-button').disabled=true;status('library-status','파일을 보관·추출하고 있습니다. 스캔 OCR은 시간이 걸릴 수 있습니다.');
  try{const params=new URLSearchParams({filename:file.name,language:form.elements.language.value,title:form.elements.title.value});const result=await api('/api/import?'+params,file,true);await loadLibrary();status('library-status',`가져오기 ${result.status==='partial'?'부분 완료 · 원본/실패 페이지 확인 필요':'완료'}. ${result.reused_version?'기존 추출 버전 재사용.':'새 원문 버전 보관.'} 파일은 로컬 DB와 연결했습니다.`);form.reset();}
  catch(error){status('library-status',`가져오기 실패. ${error.message}`,true);}
  finally{importing=false;$('import-button').disabled=false;}
});
async function openLocation(){const params=new URLSearchParams(location.hash.slice(1));if(params.get('run'))await openRun(params.get('run'),null,false,params.get('passage'),params.get('translation'));else if(params.get('passage'))await openPassage(params.get('passage'),params.get('translation'));}
window.addEventListener('hashchange',openLocation);
async function boot(){await loadLibrary();await openLocation();}
boot();
