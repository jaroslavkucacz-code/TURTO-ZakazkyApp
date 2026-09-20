#!/usr/bin/env node
/* Switching backgrounds must never rebuild CRM layers or move the camera. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const sent=[],handlers={},layers=new Map(),sources=new Map(),order=['roads','labels'];
let receive,instance;
class MapFake {
  constructor(){instance=this;this.center={lng:14.42,lat:50.08};this.zoom=17;this.cameraCalls=0;}
  addControl(){}
  on(type,...args){(handlers[type]??=[]).push(args.at(-1));}
  addSource(id,source){sources.set(id,{...source,setData(data){this.data=data;}});}
  getSource(id){return sources.get(id);}
  addLayer(layer,before){layers.set(layer.id,layer);const n=order.indexOf(before);if(n<0)order.push(layer.id);else order.splice(n,0,layer.id);}
  getLayer(id){return layers.get(id);}
  setLayoutProperty(id,k,v){(layers.get(id).layout??={})[k]=v;}
  getCenter(){return this.center;}
  getZoom(){return this.zoom;}
  getCanvas(){return {style:{}};}
  isSourceLoaded(){return true;}
  flyTo(){this.cameraCalls++;}
  fitBounds(){this.cameraCalls++;}
  resize(){}
}
class Popup {setDOMContent(){return this;}setLngLat(){return this;}addTo(){return this;}remove(){}}
class Marker extends Popup {setPopup(){return this;}togglePopup(){}}
const notice={textContent:''};
const context={document:{getElementById:()=>notice,createElement:()=>({append(){},addEventListener(){}})},
  window:{chrome:{webview:{postMessage:d=>sent.push(d),addEventListener:(_,cb)=>receive=cb}},addEventListener(){}},
  maplibregl:{Map:MapFake,NavigationControl:class{},Popup,Marker,LngLatBounds:class{extend(){return this;}}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../ZakazkyApp_base_6.1/price_lists_domain/maps/assets/map.js'),'utf8'),context);
const emit=(type,value={})=>(handlers[type]??[]).forEach(cb=>cb(value));
const command=data=>receive({data});
const latest=type=>sent.filter(x=>x.type===type).at(-1);
const data={type:'FeatureCollection',features:[{geometry:{coordinates:[14.42,50.08]},properties:{key:'project:1'}}]};
command({type:'data',data});
command({type:'basemap',value:'orthophoto'}); // Before style load.
assert.equal(sources.size,0);
emit('load');
assert.equal(layers.get('cuzk-orthophoto').layout.visibility,'visible');
assert(order.indexOf('cuzk-orthophoto')<order.indexOf('clusters'));
assert(order.indexOf('labels')<order.indexOf('cuzk-orthophoto'));
command({type:'preview',point:[14.42,50.08],label:'Parcela 1'});
command({type:'pick',value:true});
const calls=instance.cameraCalls, source=sources.get('crm');
for(const value of ['map','orthophoto','map','orthophoto']){
  command({type:'basemap',value});
  const state=latest('basemap-applied');
  assert.equal(state.value,value);assert.equal(state.count,1);assert.equal(state.picking,true);
  assert.deepEqual(Array.from(state.preview),[14.42,50.08]);
  assert.deepEqual(Array.from(state.center),[14.42,50.08]);assert.equal(state.zoom,17);
  assert.equal(sources.get('crm'),source);assert.equal(instance.cameraCalls,calls);
}
assert.equal(sources.size,2);
command({type:'basemap',value:'untrusted'});assert.equal(latest('basemap-applied').value,'orthophoto');
emit('sourcedata',{sourceId:'cuzk-orthophoto',sourceDataType:'content'});emit('idle');
assert.equal(latest('basemap-ready').value,'orthophoto');
command({type:'pick',value:false});
emit('error',{sourceId:'cuzk-orthophoto'});assert.match(notice.textContent,/Ortofoto ČR není dostupné/);
command({type:'data',data});assert.match(notice.textContent,/Ortofoto ČR není dostupné/);
command({type:'basemap',value:'map'});assert.equal(notice.textContent,'');
const errors=sent.filter(x=>x.type==='basemap-error').length;
emit('error',{sourceId:'cuzk-orthophoto'});
assert.equal(sent.filter(x=>x.type==='basemap-error').length,errors);
assert.equal(layers.get('cuzk-orthophoto').layout.visibility,'none');
console.log('8.0.37: early/rapid switches preserve CRM layers, camera, preview and picking; failures recover.');
