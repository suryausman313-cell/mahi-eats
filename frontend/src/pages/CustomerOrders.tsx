import {useEffect,useState} from 'react';
import {Link,useNavigate} from 'react-router-dom';
import {ArrowLeft,Bike,Clock3,MapPin,MessageCircle,Phone,ReceiptText,Star,Store} from 'lucide-react';
import {request} from '../api';
import CustomerBottomNav from '../components/CustomerBottomNav';

const wa=(phone:any)=>{
 const digits=String(phone||'').replace(/\D/g,'');
 return digits.startsWith('0')?`971${digits.slice(1)}`:digits;
};

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

 function openRating(o:any){
  setRatingOpen(o.id);
  setRating(Number(o.my_rating||5));
  setComment(o.my_review||'');
 }

 async function saveRating(o:any){
  if(!o.shop?.slug)return;
  setSaving(true);
  try{
   await request(`/api/public/shops/${o.shop.slug}/feedback`,{
    method:'POST',
    body:JSON.stringify({order_id:o.id,rating,comment:comment.trim()||null})
   },token);
   setMsg('Thanks! Your rating was saved.');
   setRatingOpen(null);
   await load();
  }catch(e:any){setMsg(e.message)}
  finally{setSaving(false)}
 }

 return <main className="page customerOrdersPage customerAppWithNav">
  <div>
   <Link className="back" to="/"><ArrowLeft/>Home</Link>
   <div className="eyebrow">YOUR MAHI EATS</div>
   <h1>Orders</h1>
  </div>

  {msg&&<div className="toast inlineToast">{msg}</div>}

  <div className="customerOrderList">
   {orders.map(o=>{
    const riderPhone=o.rider?.phone||o.merchant_rider_phone;
    const riderName=o.rider?.name||o.merchant_rider_name;
    const delivered=o.status==='delivered'||o.rider_status==='delivered';
    return <article className="customerOrderCard" key={o.id}>
     <div className="customerOrderTop">
      <div className="miniLogo"><Store/></div>
      <div>
       <h3>{o.shop?.name||'Shop'}</h3>
       <span>Order #{o.id}</span>
      </div>
      <span className={`statusPill ${o.status}`}>{o.status}</span>
     </div>

     <div className="customerOrderMeta">
      <span><Clock3/> {new Date(o.created_at).toLocaleString('en-AE',{timeZone:'Asia/Dubai'})}</span>
      <span><MapPin/> {o.delivery_address||'Delivery address'}</span>
     </div>

     {o.shop?.phone&&<div className="customerContactCard">
      <div><Store/><span><b>{o.shop.name}</b><small>{o.shop.phone}</small></span></div>
      <div className="contactButtons">
       <a href={`tel:${o.shop.phone}`}><Phone/>Call shop</a>
       <a href={`https://wa.me/${wa(o.shop.phone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a>
      </div>
     </div>}

     {riderPhone&&<div className="customerContactCard rider">
      <div><Bike/><span><b>{riderName||'Your rider'}</b><small>{riderPhone}</small></span></div>
      <div className="contactButtons">
       <a href={`tel:${riderPhone}`}><Phone/>Call rider</a>
       <a href={`https://wa.me/${wa(riderPhone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a>
      </div>
     </div>}

     <div className="row orderActionsRow">
      <b>AED {Number(o.total||0).toFixed(2)}</b>
      <div>
       {delivered&&<button className="rateOrderBtn" onClick={()=>openRating(o)}>
        <Star/>{o.my_rating?`${o.my_rating}/5`:'Rate shop'}
       </button>}
       <Link className="small buttonLink" to={`/track/${o.id}?phone=${encodeURIComponent(o.customer_phone)}`}>View details</Link>
      </div>
     </div>

     {ratingOpen===o.id&&<div className="ratingEditor">
      <h4>Rate {o.shop?.name||'shop'}</h4>
      <div className="starPicker">{[1,2,3,4,5].map(n=><button key={n} className={n<=rating?'active':''} onClick={()=>setRating(n)}><Star/></button>)}</div>
      <textarea value={comment} onChange={e=>setComment(e.target.value)} placeholder="Write a short review (optional)"/>
      <div className="ratingActions">
       <button onClick={()=>setRatingOpen(null)}>Cancel</button>
       <button className="save" disabled={saving} onClick={()=>void saveRating(o)}>{saving?'Saving…':'Save rating'}</button>
      </div>
     </div>}
    </article>
   })}

   {!orders.length&&!msg&&<div className="marketEmpty">
    <ReceiptText/>
    <h3>No orders yet</h3>
    <p>Your Mahi Eats orders will appear here.</p>
    <Link className="buttonLink" to="/">Browse shops</Link>
   </div>}
  </div>

  <CustomerBottomNav active="orders"/>
 </main>;
}
