/* UI state and map interactions. All predictions and exports come from the API. */
'use strict';
const $ = id => document.getElementById(id);
const state = {catalog:null, patchId:null, coverage:null, geometry:null, result:null, job:null,
  drawing:false, first:null, draft:null, preview:null, selection:null,
  overlay:null, regionalOverlay:null, stage:'empty', busy:false, planning:false, plan:null, planToken:0, lastPixelToken:0};
const map = L.map('map', {zoomControl:false, preferCanvas:true, minZoom:3, maxZoom:20});
for(const [name,zIndex] of [['regional',410],['analysis',420]]) {
  map.createPane(name);map.getPane(name).style.zIndex=zIndex;
  map.getPane(name).style.pointerEvents='none';
}
map.createPane('selection');
map.getPane('selection').style.zIndex=450;
map.getPane('selection').style.pointerEvents='none';
map.setView([49.3,-.36],15);
const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:19, attribution:'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'}).addTo(map);
L.control.scale({imperial:false,maxWidth:130}).addTo(map);
let toastTimer;

function toast(text) {
  $('toast').textContent=text; $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>{$('toast').hidden=true;},4500);
}
async function api(url, options={}) {
  const response=await fetch(url,options);
  if(!response.ok) {
    let message=`Request failed (${response.status})`;
    try {const body=await response.json(); message=typeof body.detail==='string'?body.detail:message;} catch{}
    throw new Error(message);
  }
  return response.json();
}
function setStage(stage) {
  state.stage=stage;
  for(const name of ['empty','ready','running','error']) $(name+'-state').hidden=stage!==name;
  $('results').hidden=stage!=='done';
  const running=stage==='running'||state.busy;
  $('analyze').disabled=!state.geometry||running||state.drawing||state.planning||!state.plan||(state.plan.exceeds_download_limit||state.plan.exceeds_analysis_limit);
  $('analyze').textContent=running?'Analyzing…':'Analyze selected area';
  $('select-side').disabled=running;
  $('select-map').disabled=running;
  $('season').disabled=running;
  $('available-region').disabled=running||state.drawing;
  const region=state.catalog?.patches?.find(p=>p.id===state.patchId);
  $('select-whole').hidden=state.drawing||!region;
  $('select-whole').disabled=running;
  $('select-side').textContent=state.geometry?'Reselect area':'Select area';
  $('status').hidden=stage!=='done';
  if(stage==='done') {
    $('status').replaceChildren();
    const image=document.createElement('img');image.src='/assets/check.svg';image.width=20;image.height=20;image.alt='';
    $('status').append(image,document.createTextNode(state.result?.excluded_pixels?'Analysis complete · some pixels lack usable imagery':'All selected pixels labeled'));
  }
}
function failure(error, title='Analysis unavailable') {
  $('error-title').textContent=title; $('error-message').textContent=error.message;
  state.busy=false; setStage('error');
}
function toggleSidebar(collapsed) {
  $('workspace').classList.toggle('collapsed',collapsed);
  $('expand').hidden=!collapsed;
  $('collapse').setAttribute('aria-expanded',String(!collapsed));
  $('expand').setAttribute('aria-expanded',String(!collapsed));
  requestAnimationFrame(()=>map.invalidateSize());
}
$('collapse').onclick=()=>toggleSidebar(true);
$('expand').onclick=()=>toggleSidebar(false);
let previousMapWidth=0;
new ResizeObserver(entries=>{
  const width=entries[0].contentRect.width;
  map.invalidateSize();
  // Preserve the user's view when the sidebar or viewport changes size.
  previousMapWidth=width;
}).observe($('map'));
$('zoom-in').onclick=()=>map.zoomIn();
$('zoom-out').onclick=()=>map.zoomOut();
function focusPreparedRegion(patch) {
  const bounds=L.geoJSON(patch.default_geometry||patch.geometry).getBounds();
  map.setView(bounds.getCenter(),14);
}
$('home').onclick=()=>{
  const patch=state.catalog?.patches?.find(p=>p.id===state.patchId);
  if(patch)focusPreparedRegion(patch);
  else if(state.selection)map.fitBounds(state.selection.getBounds(),{padding:[65,65]});
  else map.setView([49.3,-.36],14);
};

function clearResult() {
  if(state.overlay) {map.removeLayer(state.overlay);state.overlay=null;}
  if(state.preview) {map.removeLayer(state.preview);state.preview=null;}
  $('imagery-layer').disabled=true;$('imagery-layer').checked=false;$('preview-date').textContent='after analysis';
  state.result=null;state.job=null;state.lastPixelToken++;
  $('classification-switch').hidden=!state.regionalOverlay;$('pixel-card').hidden=true;
  $('show-results').checked=true;
  if(state.regionalOverlay&&!map.hasLayer(state.regionalOverlay))state.regionalOverlay.addTo(map);
  $('imagery').textContent=state.catalog?.mode!=='geodes'?'Prepared Sentinel‑2 time series':'THEIA / GEODES · Sentinel‑2 L2A';
  localStorage.removeItem('crop-map-last-analysis');
}
function clearSelection() {
  if(state.selection) map.removeLayer(state.selection);
  state.selection=null;state.geometry=null;
}
function selectedGeometry(geometry, prepare=true) {
  state.planToken++;state.planning=false;
  clearSelection();clearResult();
  state.geometry=geometry;
  state.selection=L.geoJSON(geometry,{pane:'selection',interactive:false,style:{color:'#fff',weight:2,fillColor:'#196449',fillOpacity:.12}}).addTo(map);
  state.selection.bindTooltip('Selected area',{permanent:true,direction:'top',className:'selection-label'});
  if(prepare)planSelection();else {state.plan=null;setStage('ready');}
}
async function planSelection() {
  if(!state.geometry||state.busy)return;
  const token=++state.planToken;
  state.planning=true;state.plan=null;
  $('ready-description').textContent='Checking available acquisitions and prepared imagery for your selection…';
  setStage('ready');
  try {
    const plan=await api('/api/imagery-plan',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({geometry:state.geometry,season:$('season').value,
        ...(state.catalog.mode!=='geodes'?{patch_id:state.patchId}:{})})});
    if(token!==state.planToken)return;
    state.plan=plan;
    if(state.catalog.mode!=='geodes') {
      const observations=plan.observation_range?.[0]!==plan.observation_range?.[1]?
        `${plan.observation_range[0]}–${plan.observation_range[1]}`:String(plan.scenes);
      $('ready-description').textContent=`${plan.selected_area_ha.toFixed(2)} ha · ${observations} observations per location · `+
        (plan.prediction_ready?'TSViT classification is ready across the region. Analyze to summarize and export your selection.':
          'TSViT uses the available time series at each location, up to 60 observations. Imagery is ready; no satellite download is needed.')+
        (plan.exceeds_analysis_limit?` Select a smaller area: at most ${plan.max_analysis_windows} windows per analysis.`:'')+
        (plan.valid_area_ha<plan.selected_area_ha?` ${plan.valid_area_ha.toFixed(2)} ha have sufficient valid imagery.`:'');
      $('imagery').textContent=`${plan.source} · ${plan.first_date} – ${plan.last_date}`;
      const {bounds}=await api(`/api/patches/${plan.patch_id}/preview-bounds`);
      if(token!==state.planToken)return;
      if(state.preview)map.removeLayer(state.preview);
      state.preview=L.imageOverlay(`/api/patches/${plan.patch_id}/preview`,bounds,{opacity:1,zIndex:250}).addTo(map);
      $('preview-date').textContent=plan.preview_date;
      $('imagery-layer').disabled=false;$('imagery-layer').checked=true;
      return;
    }
    const pending=plan.scenes-plan.cached_scenes;
    let description=`${plan.scenes} candidate acquisitions · ${plan.cached_scenes} already prepared. `;
    if(pending) description+=`GEODES requires whole-scene downloads: approximately ${plan.estimated_download_gb.toFixed(2)} GB`+
      (plan.unknown_sizes?' plus products of unknown size':'')+'. The first analysis can take a long time.';
    else description+='Prepared imagery can be reused without downloading these scenes again.';
    if(plan.exceeds_download_limit) description+=` This exceeds the ${plan.download_limit_gb} GB local download limit. Prepare imagery in advance or adjust the server configuration.`;
    $('ready-description').textContent=description;
  } catch(error) {
    if(token===state.planToken)failure(error,'Could not prepare this selection');
  } finally {
    if(token===state.planToken){state.planning=false;setStage(state.stage);}
  }
}
$('season').onchange=()=>{if(state.geometry){clearResult();planSelection();}};
let reselectAction;
function requestReselect(action) {
  if(state.stage==='running')return;
  if(state.result) {reselectAction=action;$('confirm-dialog').showModal();}
  else action();
}
function showCoverage(patch) {
  if(!state.coverage)return;
  state.coverage.clearLayers();
  state.coverage.addData({type:'Feature',geometry:patch.geometry,properties:{id:patch.id}});
}
function choosePatch(id) {
  const patch=state.catalog.patches.find(p=>p.id===Number(id));
  if(!patch)return;
  state.patchId=patch.id;$('available-region').value=String(patch.id);
  if(state.regionalOverlay)map.removeLayer(state.regionalOverlay);
  state.regionalOverlay=null;
  $('select-whole').hidden=false;
  $('data-description').textContent='Available regions use prepared satellite imagery. TSViT runs when you press Analyze.';
  showCoverage(patch);
  stopDrawing();selectedGeometry(patch.default_geometry||patch.geometry);
  focusPreparedRegion(patch);
}
$('select-whole').onclick=()=>requestReselect(()=>{
  const patch=state.catalog.patches.find(p=>p.id===state.patchId);
  if(patch){selectedGeometry(patch.geometry);map.fitBounds(state.coverage.getBounds(),{padding:[65,65]});}
});
$('available-region').onchange=()=>{
  const next=$('available-region').value;
  $('available-region').value=String(state.patchId);
  requestReselect(()=>choosePatch(next));
};
$('confirm-reselect').onclick=()=>{
  $('confirm-dialog').close();clearResult();clearSelection();
  const action=reselectAction;reselectAction=null;if(action)action();
};
function startDrawing() {
  state.drawing=true;state.first=null;
  setStage(state.geometry?'ready':'empty');
  $('workspace').classList.add('drawing');$('draw-cancel').hidden=false;
  $('map-message').textContent=state.catalog.mode!=='geodes'?'Click two corners inside the outlined region.':'Click two opposite corners to select your area.';$('map-message').hidden=false;
  map.doubleClickZoom.disable();
}
function stopDrawing() {
  state.drawing=false;state.first=null;
  if(state.draft)map.removeLayer(state.draft);state.draft=null;
  $('workspace').classList.remove('drawing');$('draw-cancel').hidden=true;$('map-message').hidden=true;
  map.doubleClickZoom.enable();
  if(!state.busy&&state.stage!=='running')setStage(state.stage);
}
const selectAction=()=>requestReselect(startDrawing);
$('select-map').onclick=selectAction;$('select-side').onclick=selectAction;
$('draw-cancel').onclick=stopDrawing;
function rectangle(first,second) {
  const south=Math.min(first.lat,second.lat),north=Math.max(first.lat,second.lat);
  const west=Math.min(first.lng,second.lng),east=Math.max(first.lng,second.lng);
  return {type:'Polygon',coordinates:[[[west,north],[east,north],[east,south],[west,south],[west,north]]]};
}
map.on('mousemove',event=>{
  if(!state.drawing||!state.first)return;
  const bounds=L.latLngBounds(state.first,event.latlng);
  if(state.draft)state.draft.setBounds(bounds);
  else state.draft=L.rectangle(bounds,{pane:'selection',color:'#fff',weight:2,fillOpacity:.15,interactive:false}).addTo(map);
});
map.on('click',async event=>{
  if(state.drawing) {
    if(!state.first) {state.first=event.latlng;$('map-message').textContent='Click the opposite corner to finish your selection.';return;}
    const geometry=rectangle(state.first,event.latlng);
    stopDrawing();selectedGeometry(geometry);return;
  }
  if((state.result||state.regionalOverlay)&&$('show-results').checked) {
    const token=++state.lastPixelToken;
    try {
      let crop;
      if(state.result) {
        try {crop=await api(`/api/analyses/${state.result.id}/pixel?lat=${event.latlng.lat}&lng=${event.latlng.lng}`);}
        catch(error) {if(!state.regionalOverlay)throw error;}
      }
      if(!crop)crop=await api(`/api/patches/${state.patchId}/pixel?lat=${event.latlng.lat}&lng=${event.latlng.lng}`);
      if(token!==state.lastPixelToken)return;
      showCrop(crop);
    } catch {if(token===state.lastPixelToken)$('pixel-card').hidden=true;}
  }
});
function showCrop(crop) {
  $('pixel-name').replaceChildren();
  const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=crop.color;
  $('pixel-name').append(swatch,document.createTextNode(crop.name));
  $('pixel-card').hidden=false;
}
$('pixel-close').onclick=()=>{$('pixel-card').hidden=true;state.lastPixelToken++;};
async function analyze() {
  if(!state.geometry||state.busy||state.stage==='running'||state.planning||!state.plan||(state.plan.exceeds_download_limit||state.plan.exceeds_analysis_limit))return;
  state.busy=true;clearResult();setStage('running');$('progress').value=0;$('progress-percent').textContent='0%';
  try {
    const request={season:$('season').value,geometry:state.geometry,
      ...(state.catalog.mode!=='geodes'?{patch_id:state.patchId}:{})};
    const response=await api('/api/analyses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    if(response.cached)toast('Showing the saved prediction for this area and model.');
    state.job=response.id;localStorage.setItem('crop-map-last-analysis',response.id);
    await poll(response.id);
  } catch(error) {failure(error);}
}
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function poll(id) {
  let errors=0;
  for(;;) {
    let response;
    try {response=await api(`/api/analyses/${id}`);errors=0;}
    catch(error) {if(++errors>=3)throw error;await pause(1500);continue;}
    if(state.job!==id)return;
    $('progress').value=response.progress;$('progress-percent').textContent=`${response.progress}%`;
    let message=response.message;
    if(response.scene_download_percent!=null)message+=` · current scene ${response.scene_download_percent.toFixed(1)}%`;
    if(response.downloaded_mb)message+=` · ${(response.downloaded_mb/1024).toFixed(2)} GB received`;
    if(response.download_mbps)message+=` · ${response.download_mbps.toFixed(1)} MB/s`;
    if(response.started_at)message+=` · ${Math.floor((Date.now()/1000-response.started_at)/60)} min elapsed`;
    $('progress-message').textContent=message;
    if(response.phase==='quota')$('progress-label').textContent='Waiting for GEODES quota';
    else $('progress-label').textContent=response.phase==='inference'?'TSViT crop classification':response.phase==='export'?'Preparing results':'Satellite imagery preparation';
    if(response.status==='done') {state.busy=false;renderResult(response.result);return;}
    if(response.status==='error')throw new Error(response.message);
    if(response.status==='cancelled') {state.busy=false;setStage(state.geometry?'ready':'empty');toast('Analysis cancelled');return;}
    await pause(400);
  }
}
$('analyze').onclick=analyze;$('retry').onclick=()=>state.catalog&&state.geometry?planSelection():boot();
$('cancel-analysis').onclick=async()=>{
  if(!state.job)return;
  try {await api(`/api/analyses/${state.job}`,{method:'DELETE'});$('progress-message').textContent='Cancelling analysis…';}
  catch(error){toast(error.message);}
};
function renderResult(result) {
  state.result=result;
  if(state.overlay)map.removeLayer(state.overlay);
  state.overlay=L.imageOverlay(`/api/analyses/${result.id}/overlay.png`,result.overlay_bounds,{pane:'analysis',opacity:Number($('opacity').value),zIndex:400});
  if($('show-results').checked)state.overlay.addTo(map);
  $('classification-switch').hidden=false;
  const table=$('crop-table');table.replaceChildren();
  for(const crop of result.classes) {
    const row=document.createElement('button');row.className='crop-row';
    const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=crop.color;
    const name=document.createElement('span');name.className='crop-name';name.textContent=crop.name;
    const area=document.createElement('span');area.className='crop-area';area.textContent=`${crop.area_ha.toFixed(2)} ha`;
    row.append(swatch,name,area);
    row.onclick=()=>showCrop(crop,`${crop.area_ha.toFixed(2)} ha · ${crop.percent.toFixed(1)}% of the analyzed pixels`);
    table.append(row);
  }
  $('total-area').textContent=`${result.area_ha.toFixed(2)} ha`;
  const observationNote=result.observation_range&&result.observation_range[0]!==result.observation_range[1]?
    `${result.observation_range[0]}–${result.observation_range[1]} observations per location`:`${result.observations} observations`;
  $('result-note').textContent=`TSViT predictions · 10 m pixels · ${observationNote}`+
    (result.reused_prediction?' · saved classification':'')+
    (result.excluded_pixels?` · ${(result.excluded_pixels*.01).toFixed(2)} ha excluded: insufficient valid imagery`:'');
  $('imagery').textContent=`${result.source||'PASTIS'} · ${result.dates[0]} – ${result.dates.at(-1)}`;
  if(result.preview_bounds) {
    state.preview=L.imageOverlay(`/api/analyses/${result.id}/preview.png`,result.preview_bounds,{opacity:1,zIndex:250});
    $('preview-date').textContent=result.preview_date;$('imagery-layer').disabled=false;
    if($('imagery-layer').checked)state.preview.addTo(map);
  }
  if(state.selection) {
    state.selection.setStyle({fillOpacity:0,color:'#fff',weight:2});
    state.selection.setTooltipContent(`Selected area: ${(result.selected_area_ha??result.area_ha).toFixed(2)} ha`);
  }
  setStage('done');
}
$('show-results').onchange=()=>{
  for(const layer of [state.overlay,state.regionalOverlay])if(layer) {
    if($('show-results').checked)layer.addTo(map);else map.removeLayer(layer);
  }
  if(!$('show-results').checked)$('pixel-card').hidden=true;
};
$('layers-button').onclick=()=>{
  $('layers-panel').hidden=!$('layers-panel').hidden;
  $('layers-button').setAttribute('aria-expanded',String(!$('layers-panel').hidden));
};
for(const [control,layer] of [['satellite-layer',()=>satellite],['imagery-layer',()=>state.preview]]) {
  $(control).onchange=()=>{const item=layer();if(!item)return;if($(control).checked)item.addTo(map);else map.removeLayer(item);};
}
$('opacity').oninput=()=>{for(const layer of [state.overlay,state.regionalOverlay])if(layer)layer.setOpacity(Number($('opacity').value));};
satellite.on('tileerror',()=>{if(!state.preview)return;if(!$('imagery-layer').checked){$('imagery-layer').checked=true;state.preview.addTo(map);}});
$('export').onclick=()=>{
  if(!state.result)return;
  $('export-description').textContent=`Selected area: ${state.result.area_ha.toFixed(2)} ha · Season: ${state.result.season}`;
  $('download-error').hidden=true;$('export-dialog').showModal();
};
for(const button of document.querySelectorAll('.dialog-close'))button.onclick=()=>button.closest('dialog').close();
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',event=>{
  const box=dialog.getBoundingClientRect();
  if(event.target===dialog&&(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom))dialog.close();
});
$('download').onclick=async()=>{
  if(!state.result)return;
  const formats=new Set([$ ('export-format').value]);
  if($('include-csv').checked)formats.add('csv');
  if($('include-png').checked)formats.add('png');
  const format=formats.size===1?[...formats][0]:'zip';
  const query=format==='zip'?`?include=${[...formats].join(',')}`:'';
  $('download').disabled=true;$('download').textContent='Preparing…';$('download-error').hidden=true;
  try {
    const response=await fetch(`/api/analyses/${state.result.id}/download/${format}${query}`);
    if(!response.ok)throw new Error('Download failed. Please try again.');
    const blob=await response.blob();const url=URL.createObjectURL(blob);
    const link=document.createElement('a');link.href=url;link.download=`crop-map-${state.result.patch_id||state.result.id}.${format==='tif'?'tif':format}`;
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    $('export-dialog').close();$('download-dialog').showModal();
  } catch(error) {$('download-error').textContent=error.message;$('download-error').hidden=false;}
  finally {$('download').disabled=false;$('download').textContent='Download';}
};
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.drawing)stopDrawing();});
async function boot() {
  try {
    const last=localStorage.getItem('crop-map-last-analysis');
    state.catalog=await api('/api/catalog');$('season').replaceChildren();
    for(const season of state.catalog.seasons) {
      const option=document.createElement('option');option.value=season;
      option.textContent=season;$('season').append(option);
    }
    $('season').value=state.catalog.seasons.includes('2018–2019')?'2018–2019':state.catalog.seasons[0];
    if(state.catalog.mode!=='geodes') {
      const patches=state.catalog.patches;
      $('source-status').textContent=`${patches.length} prepared regions · 10 m imagery`;
      $('coverage-control').hidden=!patches.length;
      $('available-region').replaceChildren();
      for(const patch of patches) {
        const option=document.createElement('option');option.value=patch.id;
        option.textContent=patch.name;$('available-region').append(option);
      }
      if(state.coverage)map.removeLayer(state.coverage);
      state.coverage=L.geoJSON({type:'FeatureCollection',features:patches.map(p=>({type:'Feature',geometry:p.geometry,properties:{id:p.id,name:p.name}}))},
        {interactive:false,style:{color:'#78a754',weight:2,dashArray:'6 4',fillOpacity:.04}}).addTo(map);
      if(!patches.length)throw new Error('No demo imagery is installed. Prepare Sentinel-2 data on the server first.');
      choosePatch(patches[0].id);
    } else {
      $('source-status').textContent=state.catalog.source.configured?'Imagery source connected':'Imagery source needs an API key · ';
      $('empty-description').textContent='Select two opposite corners on the map, then choose a season to identify its crops.';
      $('data-description').textContent='Analysis fetches THEIA imagery. Processing starts when you press Analyze.';
    }
    if(state.catalog.mode==='geodes'&&!state.catalog.source.configured) {
      const link=document.createElement('a');link.href=state.catalog.source.setup_url;link.textContent='Create a key';link.target='_blank';link.rel='noopener';$('source-status').append(link);
    }
    if(state.catalog.mode==='geodes')setStage('empty');
    if(last) {
      try {
        const response=await api(`/api/analyses/${last}`);
        const restoredPatch=response.result?.patch_id??response.request?.patch_id;
        if(state.catalog.mode!=='geodes') {
          if(!state.catalog.patches.some(p=>p.id===restoredPatch))throw new Error('Saved analysis belongs to another data source.');
          choosePatch(restoredPatch);
        }
        if(['queued','running'].includes(response.status)) {
          $('season').value=response.request.season;
          selectedGeometry(response.request.geometry,false);map.fitBounds(state.selection.getBounds(),{padding:[65,65]});
          state.job=last;state.busy=true;setStage('running');await poll(last);
        }
      } catch(error) {
        localStorage.removeItem('crop-map-last-analysis');
        if(state.busy)failure(error);
      }
    }
  } catch(error) {failure(error,'Could not load available imagery');}
}
boot();
