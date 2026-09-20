/* CRM data arrives only through the private WebView2 message channel. */
'use strict';
const empty = () => ({type:'FeatureCollection',features:[]});
let dataset=empty(), picking=false, popup=null, loaded=false;
let previewPoint=null, previewLabel='', previewMarker=null;
let basemap='map', basemapNotice='', orthoContent=false, orthoError=false, readyBasemap=null;
const ORTHO='cuzk-orthophoto';
const notice=document.getElementById('notice');
const send = data => window.chrome.webview.postMessage(data);
const map=new maplibregl.Map({container:'map',style:'https://tiles.openfreemap.org/styles/liberty',
  center:[15.4,49.8],zoom:6,attributionControl:true});
map.addControl(new maplibregl.NavigationControl(),'top-right');
function updateNotice(){
  notice.textContent=picking?'Klikněte na místo pro vybraný záznam. Uložení ještě potvrdíte v CRM.':basemapNotice;
}
function applyBasemap(){
  if(!loaded)return;
  if(basemap==='orthophoto'&&!map.getSource(ORTHO)){
    map.addSource(ORTHO,{type:'raster',tileSize:256,minzoom:6,maxzoom:20,
      bounds:[11.87,48.20,19.14,51.45],
      tiles:['https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer/tile/{z}/{y}/{x}'],
      attribution:'Ortofoto ČR © <a href="https://geoportal.cuzk.gov.cz/" target="_blank" rel="noopener">ČÚZK</a>'});
    // Keep the original map beneath the imagery outside Czech coverage, and
    // every CRM layer above it. Never replace the style or change the camera.
    map.addLayer({id:ORTHO,type:'raster',source:ORTHO,layout:{visibility:'none'},
      paint:{'raster-fade-duration':0}},'clusters');
  }
  if(map.getLayer(ORTHO))map.setLayoutProperty(ORTHO,'visibility',basemap==='orthophoto'?'visible':'none');
  readyBasemap=null;orthoError=false;
  basemapNotice=basemap==='orthophoto'?'Načítám ortofoto ČR… Mimo jeho pokrytí zůstává běžná mapa.':'';
  updateNotice();
  const center=map.getCenter();
  send({type:'basemap-applied',value:basemap,center:[center.lng,center.lat],zoom:map.getZoom(),
    count:dataset.features.length,preview:previewPoint,picking});
}
map.on('sourcedata',e=>{
  if(e.sourceId===ORTHO&&e.sourceDataType==='content')orthoContent=true;
});
map.on('idle',()=>{
  if(!loaded||readyBasemap===basemap)return;
  if(basemap==='orthophoto'&&(!orthoContent||orthoError||!map.isSourceLoaded(ORTHO)))return;
  readyBasemap=basemap;basemapNotice='';updateNotice();
  send({type:'basemap-ready',value:basemap});
});
function preview(fly=true){
  if(previewMarker){previewMarker.remove();previewMarker=null;}
  if(!previewPoint){send({type:'preview-applied',point:null});return;}
  if(!loaded)return;
  const content=document.createElement('div');
  const title=document.createElement('strong');title.textContent=previewLabel;content.append(title);
  const hint=document.createElement('p');hint.textContent='Náhled – uložení potvrďte v CRM.';content.append(hint);
  previewMarker=new maplibregl.Marker({color:'#ad42bc'}).setLngLat(previewPoint)
    .setPopup(new maplibregl.Popup().setDOMContent(content)).addTo(map);
  previewMarker.togglePopup();
  if(fly)map.flyTo({center:previewPoint,zoom:Math.max(map.getZoom(),17)});
  send({type:'preview-applied',point:previewPoint});
}
function fit(){
  if(!dataset.features.length)return;
  const bounds=new maplibregl.LngLatBounds();
  dataset.features.forEach(f=>bounds.extend(f.geometry.coordinates));
  map.fitBounds(bounds,{padding:65,maxZoom:15,duration:450});
}
function info(feature){
  if(popup)popup.remove();
  const p=feature.properties, node=document.createElement('div');
  const title=document.createElement('strong');title.textContent=p.title;node.append(title);
  [p.address, p.kind==='company'?'Společnost':`Akce · ${p.phase}${p.supplying?' · Dodáváme':''}`].forEach(text=>{
    const line=document.createElement('p');line.textContent=text;node.append(line);
  });
  const button=document.createElement('button');button.textContent='Otevřít záznam v CRM';
  button.addEventListener('click',()=>send({type:'open',key:p.key}));node.append(button);
  popup=new maplibregl.Popup().setLngLat(feature.geometry.coordinates).setDOMContent(node).addTo(map);
  send({type:'select',key:p.key});
}
map.on('load',()=>{
  loaded=true;
  map.addSource('crm',{type:'geojson',data:dataset,cluster:true,clusterRadius:42,clusterMaxZoom:13});
  map.addLayer({id:'clusters',type:'circle',source:'crm',filter:['has','point_count'],paint:{'circle-color':'#527784','circle-radius':20,'circle-stroke-color':'#fff','circle-stroke-width':2}});
  map.addLayer({id:'counts',type:'symbol',source:'crm',filter:['has','point_count'],layout:{'text-field':['get','point_count_abbreviated'],'text-font':['Noto Sans Regular'],'text-size':12},paint:{'text-color':'#fff'}});
  map.addLayer({id:'pins',type:'circle',source:'crm',filter:['!',['has','point_count']],paint:{'circle-radius':8,
    'circle-color':['case',['==',['get','kind'],'company'],'#3176b7',['get','supplying'],'#258966',['==',['get','phase'],'Ukončeno'],'#7e8794',['==',['get','phase'],'Zrušeno'],'#a591a0','#da9b36'],
    'circle-stroke-color':'#fff','circle-stroke-width':2}});
  map.on('click','clusters',async e=>{
    if(picking)return;
    const f=e.features[0], zoom=await map.getSource('crm').getClusterExpansionZoom(f.properties.cluster_id);
    map.easeTo({center:f.geometry.coordinates,zoom});
  });
  map.on('click','pins',e=>{if(!picking)info(e.features[0]);});
  ['pins','clusters'].forEach(id=>{
    map.on('mouseenter',id,()=>{if(!picking)map.getCanvas().style.cursor='pointer';});
    map.on('mouseleave',id,()=>{map.getCanvas().style.cursor=picking?'crosshair':'';});
  });
  applyBasemap();if(previewPoint)preview();else fit();send({type:'loaded'});
});
map.on('click',e=>{if(picking){picking=false;map.getCanvas().style.cursor='';updateNotice();send({type:'picked',lat:e.lngLat.lat,lon:e.lngLat.lng});}});
map.on('error',e=>{
  if(e.sourceId===ORTHO){
    if(basemap!=='orthophoto')return;
    orthoError=true;
    basemapNotice='Ortofoto ČR není dostupné. Zvolte Mapu nebo klikněte na Obnovit zobrazení.';
    updateNotice();send({type:'basemap-error',message:basemapNotice});
  }else{
    basemapNotice='Mapový podklad není dostupný. Zkontrolujte internet a klikněte na Obnovit zobrazení.';
    updateNotice();send({type:'tile-error'});
  }
});
window.chrome.webview.addEventListener('message',event=>{
  const d=event.data;
  if(d.type==='data'){
    dataset=d.data;if(popup)popup.remove();picking=false;map.getCanvas().style.cursor='';
    if(loaded){map.getSource('crm').setData(dataset);updateNotice();}
    send({type:'data-applied',count:dataset.features.length});
  }else if(d.type==='basemap'){
    if(d.value==='map'||d.value==='orthophoto'){basemap=d.value;applyBasemap();}
  }else if(d.type==='preview'){
    const p=d.point;
    previewPoint=Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90?p:null;
    previewLabel=String(d.label||'');preview();
  }else if(d.type==='fit'){fit();}
  else if(d.type==='focus'){
    const f=dataset.features.find(f=>f.properties.key===d.key);if(f){map.flyTo({center:f.geometry.coordinates,zoom:Math.max(map.getZoom(),15)});info(f);}
  }else if(d.type==='pick'){
    picking=!!d.value;updateNotice();
    map.getCanvas().style.cursor=picking?'crosshair':'';
  }else if(d.type==='reload'){location.reload();}
});
window.addEventListener('resize',()=>map.resize());
window.addEventListener('error',()=>send({type:'error',message:'Mapové okno narazilo na chybu. Obnovte zobrazení.'}));
send({type:'ready'});
