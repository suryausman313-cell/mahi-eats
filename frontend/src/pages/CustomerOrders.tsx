import {useEffect,useMemo,useState} from 'react';
import {Link,useNavigate} from 'react-router-dom';
import {ArrowLeft,Bike,CheckCircle2,Clock3,MapPin,MessageCircle,Phone,ReceiptText,Star,Store} from 'lucide-react';
import {request} from '../api';
import CustomerBottomNav from '../components/CustomerBottomNav';

const wa=(phone:any)=>{
 const digits=String(phone||'').replace(/\D/g,'');
 return digits.startsWith('0')?`971${digits.slice(1)}`:digits;
};
const delivered=(o:any)=>o.status==='delivered'||o.rider_status==='delivered';
const finished=(o:any)=>delivered(o)||o.status==='cancelled';

export default function CustomerOrders(){
 const nav=useNavigate();
 const token=localStorage.getItem('customer_token')||'';
 const [orders,setOrders]=useState<any[]>([]);
 const [msg,setMsg]=useState('');
 const [ratingOpen,setRatingOpen]=useState<number|null>(null);
 const [rating,setRating]=useState(5);
 const [comment,setComment]=useState('');
 const [saving,setSaving]=useState(false);

 async function load(){
  if(!token){nav('/account?return=/orders');return}
  try{setOrders(await request('/api/customer/orders',{},token));setMsg('')}
  catch(e:any){setMsg(e.message)}
 }
 useEffect(()=>{void load()},[]);

 const active=useMemo(()=>orders.filter(o=>!finished(o)),[orders]);
 const completed=useMemo(()=>orders.filter(finished),[orders]);
 const unrated=useMemo(()=>completed.find(o=>delivered(o)&&!o.my_rating),[completed]);

 function openRating(o:any){
  setRatingOpen(o.id);
  setRating(Number(o.my_rating||5));
  setComment(o.my_review||'');
  setTimeout(()=>document.getElementById(`rate-${o.id}`)?.scrollIntoView({behavior:'smooth',block:'center'}),30);
 }
 async function saveRating(o:any){
  if(!o.shop?.slug)return;
  setSaving(true);
  try{
   await request(`/api/public/shops/${o.shop.slug}/feedback`,{
    method:'POST',body:JSON.stringify({order_id:o.id,rating,comment:comment.trim()||null})
   },token);
   setMsg('Thanks! Your rating and feedback were saved.');
   setRatingOpen(null);
   await load();
  }catch(e:any){setMsg(e.message)}
  finally{setSaving(false)}
 }

 function card(o:any){
  const riderPhone=o.rider?.phone||o.merchant_rider_phone;
  const riderName=o.rider?.name||o.merchant_rider_name;
  const done=delivered(o);
  return <article className={`customerOrderCard ${done?'completedOrderCard':''}`} key={o.id}>
   <div className="customerOrderTop">
    <div className="miniLogo">{o.shop?.logo_url?<img src={o.shop.logo_url} alt=""/>:<Store/>}</div>
    <div><h3>{o.shop?.name||'Shop'}</h3><span>Order #{o.id}</span></div>
    <span className={`statusPill ${o.status}`}>{done?'Delivered':o.status}</span>
   </div>
   <div className="customerOrderMeta">
    <span><Clock3/> {new Date(o.created_at).toLocaleString('en-AE',{timeZone:'Asia/Dubai'})}</span>
    <span><MapPin/> {o.delivery_address||'Delivery address'}</span>
   </div>

   {o.shop?.phone&&<div className="customerContactCard">
    <div><Store/><span><b>{o.shop.name}</b><small>{o.shop.phone}</small></span></div>
    <div className="contactButtons"><a href={`tel:${o.shop.phone}`}><Phone/>Call shop</a><a href={`https://wa.me/${wa(o.shop.phone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a></div>
   </div>}

   {riderPhone&&<div className="customerContactCard rider">
    <div><Bike/><span><b>{riderName||'Your rider'}</b><small>{riderPhone}</small></span></div>
    <div className="contactButtons"><a href={`tel:${riderPhone}`}><Phone/>Call rider</a><a href={`https://wa.me/${wa(riderPhone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a></div>
   </div>}

   {done&&<div className="completedOrderBanner"><CheckCircle2/><span><b>Order completed</b><small>{o.my_rating?`You rated this shop ${o.my_rating}/5`:'How was your order? Rate the shop below.'}</small></span></div>}

   <div className="row orderActionsRow">
    <b className="orderTotalLarge">AED {Number(o.total||0).toFixed(2)}</b>
    <div>
     {done&&<button className={`rateOrderBtn ${!o.my_rating?'needsRating':''}`} onClick={()=>openRating(o)}><Star/>{o.my_rating?`Rated ${o.my_rating}/5`:'Rate this order'}</button>}
     <Link className="small buttonLink" to={`/track/${o.id}?phone=${encodeURIComponent(o.customer_phone)}`}>View details</Link>
    </div>
   </div>

   {ratingOpen===o.id&&<div className="ratingEditor customerRatingEditor" id={`rate-${o.id}`}>
    <h4>Rate {o.shop?.name||'shop'}</h4>
    <p>Tap 1–5 stars. Your rating will show on the shop page.</p>
    <div className="starPicker">{[1,2,3,4,5].map(n=><button type="button" key={n} className={n<=rating?'active':''} onClick={()=>setRating(n)} aria-label={`${n} stars`}><Star/></button>)}</div>
    <textarea value={comment} onChange={e=>setComment(e.target.value)} placeholder="Write your feedback (optional)"/>
    <div className="ratingActions"><button type="button" onClick={()=>setRatingOpen(null)}>Cancel</button><button type="button" className="save" disabled={saving} onClick={()=>void saveRating(o)}>{saving?'Saving…':'Submit rating'}</button></div>
   </div>}
  </article>;
 }

 return <main className="page customerOrdersPage customerAppWithNav">
  <div className="customerOrdersHeader"><Link className="back" to="/"><ArrowLeft/>Home</Link><div className="eyebrow">YOUR MAHI EATS</div><h1>Orders</h1><p>Active deliveries and all completed orders stay here.</p></div>
  {msg&&<div className="toast inlineToast">{msg}</div>}

  {unrated&&<button className="rateReminder" onClick={()=>openRating(unrated)}><Star/><span><b>Rate your last order</b><small>{unrated.shop?.name} · Order #{unrated.id}</small></span><strong>Rate now</strong></button>}

  <section className="customerOrdersSection"><div className="ordersSectionTitle"><div><span>ACTIVE</span><h2>Current orders</h2></div><b>{active.length}</b></div><div className="customerOrderList">{active.map(card)}{!active.length&&<div className="ordersMiniEmpty">No active orders right now.</div>}</div></section>

  <section className="customerOrdersSection completedOrdersSection"><div className="ordersSectionTitle"><div><span>HISTORY</span><h2>Completed orders</h2></div><b>{completed.length}</b></div><div className="customerOrderList">{completed.map(card)}{!completed.length&&<div className="ordersMiniEmpty">Your completed orders will appear here.</div>}</div></section>

  {!orders.length&&!msg&&<div className="marketEmpty"><ReceiptText/><h3>No orders yet</h3><p>Your Mahi Eats orders will appear here.</p><Link className="buttonLink" to="/">Browse shops</Link></div>}
  <CustomerBottomNav active="orders"/>
 </main>;
}
