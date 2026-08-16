import {useEffect,useRef,useState} from 'react';
import {LocateFixed,MapPin,X} from 'lucide-react';

type Point={latitude:number;longitude:number};
type Props={
 open:boolean;
 initial?:Point|null;
 title?:string;
 onClose:()=>void;
 onConfirm:(point:Point)=>void;
};

declare global { interface Window { L?:any; } }

let leafletPromise:Promise<any>|null=null;
function loadLeaflet(){
 if(window.L)return Promise.resolve(window.L);
 if(leafletPromise)return leafletPromise;
 leafletPromise=new Promise((resolve,reject)=>{
  if(!document.querySelector('link[data-mahi-leaflet]')){
   const link=document.createElement('link');
   link.rel='stylesheet';link.href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';link.setAttribute('data-mahi-leaflet','1');document.head.appendChild(link);
  }
  const existing=document.querySelector('script[data-mahi-leaflet]') as HTMLScriptElement|null;
  if(existing){existing.addEventListener('load',()=>resolve(window.L));existing.addEventListener('error',reject);return}
  const script=document.createElement('script');
  script.src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';script.async=true;script.setAttribute('data-mahi-leaflet','1');
  script.onload=()=>resolve(window.L);script.onerror=reject;document.body.appendChild(script);
 });
 return leafletPromise;
}

export default function LocationPicker({open,initial,title='Select location',onClose,onConfirm}:Props){
 const mapRef=useRef<HTMLDivElement|null>(null),mapObj=useRef<any>(null),markerRef=useRef<any>(null);
 const [point,setPoint]=useState<Point>(initial||{latitude:25.1288,longitude:56.3265});
 const [msg,setMsg]=useState('Tap the map or drag the pin to the exact location.');
 const [locating,setLocating]=useState(false);

 useEffect(()=>{if(open&&initial)setPoint(initial)},[open,initial?.latitude,initial?.longitude]);
 useEffect(()=>{
  if(!open||!mapRef.current)return;
  let cancelled=false;
  loadLeaflet().then((L:any)=>{
   if(cancelled||!mapRef.current)return;
   if(mapObj.current){mapObj.current.remove();mapObj.current=null}
   const map=L.map(mapRef.current,{zoomControl:true,attributionControl:true}).setView([point.latitude,point.longitude],15);
   L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);
   const marker=L.marker([point.latitude,point.longitude],{draggable:true}).addTo(map);
   const update=(lat:number,lng:number)=>{const p={latitude:Number(lat.toFixed(7)),longitude:Number(lng.toFixed(7))};setPoint(p);marker.setLatLng([p.latitude,p.longitude])};
   marker.on('dragend',()=>{const p=marker.getLatLng();update(p.lat,p.lng)});
   map.on('click',(e:any)=>update(e.latlng.lat,e.latlng.lng));
   mapObj.current=map;markerRef.current=marker;
   setTimeout(()=>map.invalidateSize(),80);
  }).catch(()=>setMsg('Map could not load. You can still use current GPS location.'));
  return()=>{cancelled=true;if(mapObj.current){mapObj.current.remove();mapObj.current=null}}
 },[open]);

 function useCurrent(){
  if(!navigator.geolocation){setMsg('Location is not supported on this device.');return}
  setLocating(true);
  navigator.geolocation.getCurrentPosition(pos=>{
   const p={latitude:pos.coords.latitude,longitude:pos.coords.longitude};setPoint(p);setLocating(false);setMsg('Current GPS location selected.');
   markerRef.current?.setLatLng([p.latitude,p.longitude]);mapObj.current?.setView([p.latitude,p.longitude],16);
  },()=>{setLocating(false);setMsg('Location permission denied. Tap the map to choose manually.')},{enableHighAccuracy:true,timeout:15000,maximumAge:30000});
 }
 if(!open)return null;
 return <div className="locationPickerBack" onClick={onClose}>
  <section className="locationPickerCard" onClick={e=>e.stopPropagation()}>
   <header><div><div className="eyebrow">DELIVERY LOCATION</div><h2>{title}</h2></div><button type="button" className="ghost" onClick={onClose}><X/></button></header>
   <button type="button" className="locationGpsButton" onClick={useCurrent} disabled={locating}><LocateFixed/>{locating?'Finding location…':'Use my current location'}</button>
   <div ref={mapRef} className="locationPickerMap"/>
   <p className="locationPickerHint"><MapPin/>{msg}</p>
   <div className="locationCoords"><span>Lat <b>{point.latitude.toFixed(6)}</b></span><span>Lng <b>{point.longitude.toFixed(6)}</b></span></div>
   <button type="button" className="locationConfirm" onClick={()=>onConfirm(point)}>Use this location</button>
  </section>
 </div>
}
