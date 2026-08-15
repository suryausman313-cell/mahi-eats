import {useEffect,useMemo,useRef,useState} from 'react';
import {Bell,ChefHat,Clock3,History,RefreshCw,Volume2,VolumeX} from 'lucide-react';
import {request} from '../api';

type View='live'|'today'|'yesterday';

function elapsed(value:string){
 const seconds=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/1000));
 return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
}

export default function Kitchen(){
 const [token,setToken]=useState(localStorage.getItem('kitchen_token')||'');
 const [shop,setShop]=useState<any>(null);
 const [orders,setOrders]=useState<any[]>([]);
 const [view,setView]=useState<View>('live');
 const [msg,setMsg]=useState('');
 const [sound,setSound]=useState(localStorage.getItem('kitchen_sound')!=='off');
 const [,setTick]=useState(0);
 const audioRef=useRef<AudioContext|null>(null);
 const ringTimer=useRef<number|null>(null);

 function beep(){
  if(!sound) return;
  try{
   const Ctx=window.AudioContext||(window as any).webkitAudioContext;
   const ctx=audioRef.current||new Ctx(); audioRef.current=ctx;
   void ctx.resume();
   [880,1100,1320].forEach((f,i)=>{const o=ctx.createOscillator();const g=ctx.createGain();const start=ctx.currentTime+i*.18;o.frequency.value=f;o.connect(g);g.connect(ctx.destination);g.gain.setValueAtTime(.22,start);g.gain.exponentialRampToValueAtTime(.01,start+.14);o.start(start);o.stop(start+.15)});
  }catch{}
 }
 function stopRing(){if(ringTimer.current){window.clearInterval(ringTimer.current);ringTimer.current=null}}
 function syncRing(list:any[]){const hasNew=view==='live'&&list.some(o=>o.status==='new');if(hasNew&&sound){if(!ringTimer.current){beep();ringTimer.current=window.setInterval(beep,3200)}}else stopRing()}

 async function load(){
  if(!token)return;
  try{
   const s=await request('/api/kitchen/me',{},token); setShop(s);
   const path=view==='live'?'/api/kitchen/orders':`/api/kitchen/history?day=${view}`;
   const o=await request(path,{},token); setOrders(o); syncRing(o); setMsg('');
  }catch(e:any){setMsg(e.message)}
 }
 useEffect(()=>{load();if(!token)return;const t=window.setInterval(load,4000);return()=>{window.clearInterval(t);stopRing()}},[token,view,sound]);
 useEffect(()=>{const t=window.setInterval(()=>setTick(x=>x+1),1000);return()=>window.clearInterval(t)},[]);

 async function login(e:any){e.preventDefault();const fd=new FormData(e.currentTarget);try{beep();stopRing();const r=await request('/api/kitchen/login',{method:'POST',body:JSON.stringify({shop_slug:fd.get('shop_slug'),pin:fd.get('pin')})});localStorage.setItem('kitchen_token',r.token);setToken(r.token);setShop(r.shop)}catch(e:any){setMsg(e.message)}}
 async function status(id:number,status:string){try{await request(`/api/kitchen/orders/${id}/status`,{method:'PATCH',body:JSON.stringify({status})},token);await load()}catch(e:any){setMsg(e.message)}}
 function toggleSound(){const v=!sound;setSound(v);localStorage.setItem('kitchen_sound',v?'on':'off');if(!v)stopRing()}

 const liveCounts=useMemo(()=>({new:orders.filter(o=>o.status==='new').length,preparing:orders.filter(o=>['accepted','preparing'].includes(o.status)).length,ready:orders.filter(o=>o.status==='ready').length}),[orders]);
 if(!token)return <main className="auth darkAuth"><form className="panel kitchenLogin" onSubmit={login}><ChefHat size={42}/><h1>Kitchen</h1><p>Each shop has its own Kitchen. Use shop slug + Kitchen PIN.</p><input name="shop_slug" placeholder="Shop slug e.g. vita-napoli"/><input name="pin" type="password" placeholder="Kitchen PIN"/><button>Open Kitchen</button>{msg&&<div className="error">{msg}</div>}</form></main>;

 return <main className="kitchenPage">
  <header className="kitchenHeader"><div><div className="eyebrow">KITCHEN</div><h1>{shop?.name}</h1><small>{shop?.is_open?'Shop is OPEN':'Shop is CLOSED'}</small></div><div className="row"><button className="ghost darkGhost" onClick={toggleSound}>{sound?<Volume2/>:<VolumeX/>}</button><button className="ghost darkGhost" onClick={load}><RefreshCw/></button><button className="ghost darkGhost" onClick={()=>{stopRing();localStorage.removeItem('kitchen_token');setToken('')}}>Logout</button></div></header>
  <div className="kitchenToolbar"><div className="tabs darkTabs"><button className={view==='live'?'active':''} onClick={()=>setView('live')}><Bell/> Live</button><button className={view==='today'?'active':''} onClick={()=>setView('today')}><Clock3/> Today</button><button className={view==='yesterday'?'active':''} onClick={()=>setView('yesterday')}><History/> Yesterday</button></div>{view==='live'&&<div className="kitchenCounters"><span>New <b>{liveCounts.new}</b></span><span>Preparing <b>{liveCounts.preparing}</b></span><span>Ready <b>{liveCounts.ready}</b></span></div>}</div>
  <div className="kitchenGrid">{orders.map(o=><article className={`kitchenOrder status-${o.status}`} key={o.id}><div className="row"><div><div className="orderNo">ORDER #{o.id}</div><h2>{o.customer_name}</h2></div><b>AED {Number(o.total).toFixed(2)}</b></div><div className="kitchenTime"><Clock3 size={16}/>{new Date(o.created_at).toLocaleTimeString('en-AE',{timeZone:'Asia/Dubai',hour:'2-digit',minute:'2-digit'})} · <b>{elapsed(o.created_at)}</b></div><div className="kitchenStatusLine"><span className={`statusPill ${o.status}`}>{o.status}</span><span>{o.delivery_mode==='mahi_eats'?'Mahi Eats delivery':'Shop delivery'}</span></div><div className="kitchenItems">{o.items.map((i:any,idx:number)=><div className="row" key={`${i.name}-${idx}`}><b>{i.qty}× {i.name}</b><span>AED {Number(i.line_total).toFixed(2)}</span></div>)}</div><p className="kitchenRider">{o.delivery_mode==='mahi_eats'?(o.rider?`Mahi Eats rider: ${o.rider.name} · ${o.rider_status}`:'Mahi Eats dispatch: Waiting for Super Admin to assign rider'):(o.merchant_rider_name?`Shop rider: ${o.merchant_rider_name}`:'Shop delivery: rider not set')}</p>{view==='live'&&<div className="kitchenActions">{o.status==='new'&&<button className="acceptBtn" onClick={()=>status(o.id,'accepted')}>Accept Order</button>}{o.status==='accepted'&&<button className="prepareBtn" onClick={()=>status(o.id,'preparing')}>Start Preparing</button>}{o.status==='preparing'&&<button className="readyBtn" onClick={()=>status(o.id,'ready')}>Ready</button>}{o.status==='ready'&&<div className="readyWaiting">✓ Ready — waiting for assigned rider pickup</div>}{['new','accepted','preparing','ready'].includes(o.status)&&<button className="cancelBtn" onClick={()=>status(o.id,'cancelled')}>Cancel</button>}</div>}</article>)}{!orders.length&&<div className="kitchenEmpty"><ChefHat size={50}/><h2>{view==='live'?'No active orders':'No orders'}</h2><p>{view==='live'?'New orders will appear automatically.':''}</p></div>}</div>{msg&&<div className="toast">{msg}</div>}
 </main>
}
