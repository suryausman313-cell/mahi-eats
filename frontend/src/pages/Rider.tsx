import {useEffect,useRef,useState} from 'react';
import {Bike,CalendarDays,CheckCircle2,ChevronRight,Clock,DollarSign,LogOut,MapPin,Menu,MessageCircle,Navigation,Package,Phone,RefreshCw,Send,Store,Wallet,X} from 'lucide-react';
import {request} from '../api';

type View='orders'|'today'|'yesterday'|'finance';
type Period='today'|'yesterday'|'week'|'month'|'year'|'all'|'custom';
const money=(v:any)=>Number(v||0).toFixed(2);
const mapUrl=(lat:any,lng:any,label='Location')=>lat!=null&&lng!=null?`https://www.google.com/maps/dir/?api=1&destination=${Number(lat)},${Number(lng)}&travelmode=driving`:`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(label)}`;
const routeUrl=(shopLat:any,shopLng:any,customerLat:any,customerLng:any,label='Customer location')=>shopLat!=null&&shopLng!=null&&customerLat!=null&&customerLng!=null?`https://www.google.com/maps/dir/?api=1&origin=${Number(shopLat)},${Number(shopLng)}&destination=${Number(customerLat)},${Number(customerLng)}&travelmode=driving`:mapUrl(customerLat,customerLng,label);
const wa=(phone:any)=>{const d=String(phone||'').replace(/\D/g,'');return d.startsWith('0')?`971${d.slice(1)}`:d};
function when(v:any){if(!v)return '-';try{return new Date(v).toLocaleString('en-AE',{timeZone:'Asia/Dubai',dateStyle:'medium',timeStyle:'short'})}catch{return String(v)}}

export default function Rider(){
 const [token,setToken]=useState(localStorage.getItem('rider_token')||'');
 const [rider,setRider]=useState<any>(null);
 const [orders,setOrders]=useState<any[]>([]);
 const [history,setHistory]=useState<any[]>([]);
 const [finance,setFinance]=useState<any>(null);
 const [cash,setCash]=useState<any[]>([]);
 const [view,setView]=useState<View>('orders');
 const [period,setPeriod]=useState<Period>('today');
 const [menuOpen,setMenuOpen]=useState(false);
 const [loading,setLoading]=useState(false);
 const [msg,setMsg]=useState('');
 const [phone,setPhone]=useState('');
 const [pin,setPin]=useState('');
 const [customFrom,setCustomFrom]=useState(()=>new Date().toISOString().slice(0,10));
 const [customTo,setCustomTo]=useState(()=>new Date().toISOString().slice(0,10));
 const [cashAmount,setCashAmount]=useState('');
 const [cashNote,setCashNote]=useState('');
 const [gps,setGps]=useState<'starting'|'live'|'blocked'|'unsupported'>('starting');
 const watchRef=useRef<number|null>(null);

 async function loadActive(silent=false){
  if(!token)return;
  if(!silent)setLoading(true);
  try{
   const [me,active]=await Promise.all([request('/api/rider/me',{},token),request('/api/rider/orders',{},token)]);
   setRider(me);setOrders(active);setMsg('');
  }catch(e:any){setMsg(e.message)}finally{if(!silent)setLoading(false)}
 }
 async function loadHistory(next:'today'|'yesterday'){
  if(!token)return;setLoading(true);
  try{setHistory(await request(`/api/rider/history?period=${next}`,{},token));setMsg('')}catch(e:any){setMsg(e.message)}finally{setLoading(false)}
 }
 async function loadFinance(next:Period=period){
  if(!token)return;setLoading(true);
  try{
   const qs=new URLSearchParams({period:next});
   if(next==='custom'){qs.set('date_from',customFrom);qs.set('date_to',customTo)}
   const [f,c]=await Promise.all([request(`/api/rider/finance?${qs.toString()}`,{},token),request('/api/rider/cash-submissions',{},token)]);
   setFinance(f);setCash(c);setMsg('');
  }catch(e:any){setMsg(e.message)}finally{setLoading(false)}
 }
 async function refresh(){
  await loadActive(true);
  if(view==='today'||view==='yesterday')await loadHistory(view);
  if(view==='finance')await loadFinance(period);
 }
 useEffect(()=>{if(!token)return;void loadActive();const t=window.setInterval(()=>void refresh(),8000);return()=>window.clearInterval(t)},[token,view,period,customFrom,customTo]);
 useEffect(()=>{if(!token)return;const beat=()=>request('/api/rider/heartbeat',{method:'POST'},token).catch(()=>{});beat();const t=window.setInterval(beat,15000);return()=>window.clearInterval(t)},[token]);
 useEffect(()=>{
  if(!token)return;
  if(!navigator.geolocation){setGps('unsupported');return}
  setGps('starting');
  watchRef.current=navigator.geolocation.watchPosition(async p=>{
   setGps('live');
   try{await request('/api/rider/location',{method:'POST',body:JSON.stringify({latitude:p.coords.latitude,longitude:p.coords.longitude})},token);setRider((r:any)=>r?({...r,is_online:true,latitude:p.coords.latitude,longitude:p.coords.longitude}):r)}catch{}
  },()=>setGps('blocked'),{enableHighAccuracy:true,maximumAge:5000,timeout:15000});
  return()=>{if(watchRef.current!=null)navigator.geolocation.clearWatch(watchRef.current);watchRef.current=null}
 },[token]);

 async function login(e:any){
  e.preventDefault();setLoading(true);
  try{const r=await request('/api/rider/login',{method:'POST',body:JSON.stringify({phone,pin})});localStorage.setItem('rider_token',r.token);setToken(r.token);setRider(r.rider);setMsg('')}catch(e:any){setMsg(e.message)}finally{setLoading(false)}
 }
 async function logout(){
  try{if(token)await request('/api/rider/status',{method:'PATCH',body:JSON.stringify({is_online:false,is_available:false})},token)}catch{}
  localStorage.removeItem('rider_token');setToken('');setRider(null);setOrders([]);setHistory([]);setFinance(null);setMenuOpen(false)
 }
 async function action(order:any,status:string){
  try{await request(`/api/rider/orders/${order.id}/status`,{method:'PATCH',body:JSON.stringify({status})},token);await refresh()}catch(e:any){setMsg(e.message)}
 }
 async function submitCash(){
  const amount=Number(cashAmount);if(!Number.isFinite(amount)||amount<=0){setMsg('Enter valid cash amount');return}
  try{await request('/api/rider/cash-submissions',{method:'POST',body:JSON.stringify({amount,note:cashNote})},token);setCashAmount('');setCashNote('');setMsg('Cash sent to Super Admin for approval');await loadFinance(period)}catch(e:any){setMsg(e.message)}
 }
 function open(next:View,nextPeriod?:Period){setMenuOpen(false);setView(next);if(next==='orders')void loadActive();if(next==='today'||next==='yesterday')void loadHistory(next);if(next==='finance'){const p=nextPeriod||'today';setPeriod(p);void loadFinance(p)}}

 if(!token)return <main className="riderFaiLogin"><form className="riderFaiLoginCard" onSubmit={login}><div className="riderLoginIcon"><Bike/></div><h1>Mahi Eats Rider</h1><p>Rider login</p><label>Mobile Number<input required value={phone} onChange={e=>setPhone(e.target.value)} placeholder="05X XXX XXXX"/></label><label>PIN<input required inputMode="numeric" type="password" value={pin} onChange={e=>setPin(e.target.value)} placeholder="Enter PIN" minLength={4} maxLength={12}/></label><button disabled={loading}>{loading?'Logging in...':'Login'}</button>{msg&&<div className="riderError">{msg}</div>}</form></main>;

 return <main className="riderFaiPage"><div className="riderFaiShell">
  <header className="riderFaiHeader"><button className="riderMenuBtn" onClick={()=>setMenuOpen(true)}><Menu/></button><div className="riderAvatar">{rider?.photo_url?<img src={rider.photo_url}/>:<Bike/>}</div><div className="riderHeaderText"><div className="eyebrow">MAHI EATS RIDER</div><h1>{rider?.name}</h1><small className={gps==='live'?'gpsLive':'gpsWarn'}>{gps==='live'?'● LIVE GPS':gps==='blocked'?'● LOCATION OFF':gps==='unsupported'?'● GPS UNSUPPORTED':'● STARTING GPS'}</small></div><button className="riderRefresh" onClick={()=>void refresh()}><RefreshCw/></button></header>

  {menuOpen&&<div className="riderMenuOverlay"><button className="riderMenuShade" onClick={()=>setMenuOpen(false)}/><aside className="riderDrawer"><div className="riderDrawerHead"><div><b>Mahi Eats Rider</b><small>{rider?.name} · {rider?.phone}</small></div><button onClick={()=>setMenuOpen(false)}><X/></button></div><nav>
   <button onClick={()=>open('orders')}><span><Package/>New / Active Orders</span><ChevronRight/></button>
   <button onClick={()=>open('today')}><span><CalendarDays/>Today Orders</span><ChevronRight/></button>
   <button onClick={()=>open('yesterday')}><span><Clock/>Yesterday Orders</span><ChevronRight/></button>
   <button onClick={()=>open('finance','today')}><span><Wallet/>Earnings & Cash</span><ChevronRight/></button>
   <button onClick={()=>open('finance','month')}><span><DollarSign/>This Month</span><ChevronRight/></button>
   <button onClick={()=>open('finance','custom')}><span><CalendarDays/>Custom Date Report</span><ChevronRight/></button>
   <button onClick={()=>void refresh()}><span><RefreshCw/>Refresh</span><ChevronRight/></button>
   <button className="drawerLogout" onClick={()=>void logout()}><span><LogOut/>Logout</span><ChevronRight/></button>
  </nav><p>Main screen par sirf new/active delivery. Reports aur cash menu ke andar.</p></aside></div>}

  {view==='orders'&&<section className="riderView"><div className="riderViewTitle"><div><h2>New / Active Delivery</h2><p>Only orders assigned by Mahi Eats Super Admin</p></div><span>{orders.length}</span></div>{loading&&!orders.length?<div className="riderEmpty">Loading deliveries...</div>:orders.length===0?<div className="riderEmpty"><Bike/><b>No new delivery</b><p>New assigned order yahan automatically show hoga.</p></div>:orders.map(o=><article className="riderFaiOrder" key={o.id}>
   <div className="riderOrderTop"><div><small>ORDER</small><b>#{o.id}</b></div><span className={`riderStatus ${o.rider_status}`}>{String(o.rider_status||'assigned').replace(/_/g,' ')}</span></div>
   <div className="riderShopName"><Store/><div><b>{o.shop?.name||'Shop'}</b><small>{o.shop?.city||''}</small></div><strong>AED {money(o.total)}</strong></div>
   <div className="riderRouteCard"><div><Store/><span><b>Pickup</b><small>{o.shop?.address||o.shop?.name}</small></span><a target="_blank" rel="noreferrer" href={mapUrl(o.shop?.latitude,o.shop?.longitude,o.shop?.address||o.shop?.name)}>Shop Map</a></div><div><MapPin/><span><b>Deliver to {o.customer_name}</b><small>{o.delivery_address||'Customer location'}</small>{o.customer_latitude!=null&&<em>{Number(o.customer_latitude).toFixed(5)}, {Number(o.customer_longitude).toFixed(5)}</em>}</span><a target="_blank" rel="noreferrer" href={mapUrl(o.customer_latitude,o.customer_longitude,o.delivery_address||'Customer location')}>Customer Map</a></div></div>
   <div className="riderCustomerContact"><div><b>Customer contact</b><strong>{o.customer_name}</strong><span>{o.customer_phone}</span></div><div><a href={`tel:${o.customer_phone}`}><Phone/>Call</a><a target="_blank" rel="noreferrer" href={`https://wa.me/${wa(o.customer_phone)}`}><MessageCircle/>WhatsApp</a><a target="_blank" rel="noreferrer" href={routeUrl(o.shop?.latitude,o.shop?.longitude,o.customer_latitude,o.customer_longitude,o.delivery_address||'Customer location')}><Navigation/>Full Route</a></div>{o.delivery_distance_km!=null?<div className="riderRoadSummary"><span><b>{Number(o.delivery_distance_km).toFixed(2)} km</b><small>shop → customer by road</small></span><span><b>AED {money(o.delivery_fee)}</b><small>delivery charge</small></span></div>:<small className="gpsMissing">Road distance is not saved on this older order. New orders will show exact driving km.</small>}{o.customer_latitude==null&&<small className="gpsMissing">Exact GPS was not saved on this older order; map will search the saved address.</small>}</div>
   <div className="riderItems">{(o.items||[]).map((i:any,idx:number)=><div key={idx}><span>{i.qty}× {i.name}{i.size_name?` (${i.size_name})`:''}</span><b>AED {money(i.line_total)}</b></div>)}</div>
   <div className="riderMoneyRow"><span>Delivery fee <b>AED {money(o.delivery_fee)}</b></span><span>Payment <b>{o.payment_method}</b></span></div>
   <div className="riderMainActions"><a className="riderNavigate" target="_blank" rel="noreferrer" href={routeUrl(o.shop?.latitude,o.shop?.longitude,o.customer_latitude,o.customer_longitude,o.delivery_address||'Customer location')}><Navigation/>Open Route in Maps</a>
    {o.rider_status==='assigned'&&<><button className="accept" onClick={()=>action(o,'accepted')}>✓ Accept</button><button className="reject" onClick={()=>action(o,'rejected')}>Reject</button></>}
    {o.rider_status==='accepted'&&o.status!=='ready'&&<button className="waiting" disabled>Waiting for Kitchen Ready</button>}
    {o.rider_status==='accepted'&&o.status==='ready'&&<button className="accept" onClick={()=>action(o,'picked_up')}>🏪 Picked Up</button>}
    {o.rider_status==='picked_up'&&<button className="accept" onClick={()=>action(o,'on_the_way')}>🚗 On the Way</button>}
    {o.rider_status==='on_the_way'&&<button className="delivered" onClick={()=>action(o,'delivered')}>✓ Delivered</button>}
   </div>
  </article>)}</section>}

  {(view==='today'||view==='yesterday')&&<section className="riderView"><div className="riderViewTitle"><div><h2>{view==='today'?'Today Orders':'Yesterday Orders'}</h2><p>Only your delivered orders</p></div><span>{history.length}</span></div>{loading&&!history.length?<div className="riderEmpty">Loading...</div>:history.length===0?<div className="riderEmpty"><CheckCircle2/><b>No delivered orders</b></div>:history.map(o=><article className="riderHistoryCard" key={o.id}><div><b>Order #{o.id} · {o.shop?.name}</b><small>{o.customer_name} · {when(o.delivered_at||o.created_at)}</small></div><CheckCircle2/><div className="riderHistoryMoney"><span>Delivery Charge<b>AED {money(o.delivery_fee)}</b></span><span>Customer Total<b>AED {money(o.total)}</b></span></div></article>)}</section>}

  {view==='finance'&&<section className="riderView riderFinance"><div className="riderFinanceHead"><div><h2>Earnings & Cash</h2><p>Delivery earning and rider cash settlement</p></div><select value={period} onChange={e=>{const p=e.target.value as Period;setPeriod(p);if(p!=='custom')void loadFinance(p)}}><option value="today">Today</option><option value="yesterday">Yesterday</option><option value="week">This Week</option><option value="month">This Month</option><option value="year">This Year</option><option value="all">All Time</option><option value="custom">Custom Date</option></select></div>
   {period==='custom'&&<div className="riderCustomDates"><label>From<input type="date" value={customFrom} onChange={e=>setCustomFrom(e.target.value)}/></label><label>To<input type="date" value={customTo} onChange={e=>setCustomTo(e.target.value)}/></label><button onClick={()=>void loadFinance('custom')}>Apply</button></div>}
   {finance&&<><h3 className="financePeriodTitle">{finance.period?.label}</h3><div className="riderFinanceGrid"><div><Package/><b>{finance.totals?.delivered_orders||0}</b><span>Delivered Orders</span></div><div><Navigation/><b>AED {money(finance.totals?.delivery_charges)}</b><span>Delivery Charges</span></div><div><DollarSign/><b>AED {money(finance.totals?.rider_earnings)}</b><span>My Earning</span></div><div><Wallet/><b>AED {money(finance.totals?.cash_collected)}</b><span>Cash Collected</span></div></div>
    <div className="riderCashCard"><h3><Wallet/>Current Cash Settlement</h3><div className="riderCashGrid"><span>Cash Due<b>AED {money(finance.current_balance?.cash_due_to_admin)}</b></span><span className="approved">Approved / Given<b>AED {money(finance.current_balance?.approved_cash)}</b></span><span className="waitingCash">Waiting Admin<b>AED {money(finance.current_balance?.awaiting_approval)}</b></span><span className="pendingCash">Total Pending<b>AED {money(finance.current_balance?.total_pending_cash)}</b></span></div>{Number(finance.current_balance?.remaining_to_submit||0)>0?<div className="riderCashSubmit"><h4>Submit cash to Mahi Eats Admin</h4><input type="number" step="0.01" min="0.01" max={finance.current_balance.remaining_to_submit} placeholder={`Max AED ${money(finance.current_balance.remaining_to_submit)}`} value={cashAmount} onChange={e=>setCashAmount(e.target.value)}/><input placeholder="Optional note" value={cashNote} onChange={e=>setCashNote(e.target.value)}/><button onClick={()=>void submitCash()}><Send/>Submit Cash</button></div>:<div className="cashClear"><CheckCircle2/>No cash waiting to submit.</div>}</div>
    <div className="riderCashCard"><h3>Cash Submission History</h3>{cash.length===0?<div className="riderEmpty compact">No cash submissions yet.</div>:cash.slice(0,20).map(x=><div className="cashHistory" key={x.id}><div><b>AED {money(x.amount)}</b><small>{when(x.submitted_at)}{x.rider_note?` · ${x.rider_note}`:''}</small></div><span className={x.status}>{x.status==='pending'?'Waiting Admin':x.status}</span></div>)}</div>
   </>}
  </section>}
  {msg&&<div className="riderToast">{msg}</div>}
 </div></main>
}
