import {useEffect,useState} from 'react';
import {Link,useParams,useSearchParams} from 'react-router-dom';
import {ArrowLeft,Bike,ChefHat,CheckCircle2,MapPin,MessageCircle,PackageCheck,Phone,Store} from 'lucide-react';
import {request} from '../api';

const kitchenSteps=['new','accepted','preparing','ready','delivered'];
const labels:any={new:'Order placed',accepted:'Accepted',preparing:'Preparing',ready:'Ready for pickup',delivered:'Delivered',cancelled:'Cancelled'};
const riderLabels:any={unassigned:'Waiting for rider',assigned:'Rider assigned',accepted:'Rider accepted',picked_up:'Picked up',on_the_way:'On the way',delivered:'Delivered',cancelled:'Cancelled'};
const wa=(phone:any)=>{
 const digits=String(phone||'').replace(/\D/g,'');
 return digits.startsWith('0')?`971${digits.slice(1)}`:digits;
};
const mapLink=(lat:any,lng:any,address='')=>{
 if(lat!=null&&lng!=null)return `https://www.google.com/maps/dir/?api=1&destination=${Number(lat)},${Number(lng)}`;
 return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address||'Delivery location')}`;
};

export default function TrackOrder(){
 const {orderId}=useParams();
 const [sp]=useSearchParams();
 const [phone,setPhone]=useState(sp.get('phone')||localStorage.getItem(`track_phone_${orderId}`)||'');
 const [data,setData]=useState<any>(null);
 const [msg,setMsg]=useState('');

 async function load(){
  if(!orderId||orderId==='0'||!phone)return;
  try{
   const r=await request(`/api/public/orders/${orderId}?phone=${encodeURIComponent(phone)}`);
   setData(r);
   setMsg('');
   localStorage.setItem(`track_phone_${orderId}`,phone);
  }catch(e:any){setMsg(e.message)}
 }

 useEffect(()=>{
  void load();
  const t=setInterval(()=>void load(),5000);
  return()=>clearInterval(t);
 },[orderId,phone]);

 if(orderId==='0')return <main className="auth"><div className="panel"><h1>Track an order</h1><p>Open the tracking link shown after checkout, or enter the order URL and phone.</p><Link className="buttonLink" to="/">Back to Mahi Eats</Link></div></main>;

 const riderPhone=data?.rider?.phone||data?.merchant_rider_phone;
 const riderName=data?.rider?.name||data?.merchant_rider_name;

 return <main className="page narrow">
  <Link className="back" to="/"><ArrowLeft size={18}/>Mahi Eats</Link>
  <div className="panel">
   <div className="eyebrow">LIVE ORDER TRACKING</div>
   <h1>Order #{orderId}</h1>

   {!phone&&<>
    <p>Enter the phone number used on this order.</p>
    <input value={phone} onChange={e=>setPhone(e.target.value)} placeholder="Phone number"/>
   </>}

   {msg&&<div className="error">{msg}</div>}

   {data&&<>
    <div className="trackingShop">
     <Store/>
     <div><b>{data.shop?.name}</b><small>{data.shop?.address||''}</small></div>
    </div>

    {data.shop?.phone&&<div className="trackingContact">
     <div><Store/><span><b>Shop contact</b><small>{data.shop.phone}</small></span></div>
     <div>
      <a href={`tel:${data.shop.phone}`}><Phone/>Call</a>
      <a href={`https://wa.me/${wa(data.shop.phone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a>
     </div>
    </div>}

    <div className="timeline">
     {kitchenSteps.map((s,i)=>{
      const current=kitchenSteps.indexOf(data.status);
      const done=current>=i&&data.status!=='cancelled';
      return <div className={done?'step done':'step'} key={s}><span>{done?<CheckCircle2/>:<ChefHat/>}</span><b>{labels[s]}</b></div>
     })}
    </div>

    <div className="deliveryCard">
     <div className="row"><h2><Bike/> Delivery</h2><b>{data.delivery_mode==='mahi_eats'?'Mahi Eats':'Shop delivery'}</b></div>
     <p className="statusBig">{riderLabels[data.rider_status]||data.rider_status}</p>

     {riderPhone&&<div className="riderInfo riderInfoV10">
      {data.rider?.photo_url?<img src={data.rider.photo_url}/>:<Bike/>}
      <div>
       <b>{riderName||'Your rider'}</b>
       <a href={`tel:${riderPhone}`}><Phone size={14}/>{riderPhone}</a>
       {data.rider?.latitude!=null&&<span><MapPin size={14}/>Live location available</span>}
      </div>
      <div className="riderCustomerActions">
       <a href={`tel:${riderPhone}`}><Phone/>Call rider</a>
       <a href={`https://wa.me/${wa(riderPhone)}`} target="_blank" rel="noreferrer"><MessageCircle/>WhatsApp</a>
       {data.rider?.latitude!=null&&<a href={mapLink(data.rider.latitude,data.rider.longitude,'Rider location')} target="_blank" rel="noreferrer"><MapPin/>Track live map</a>}
      </div>
     </div>}

     {!riderPhone&&data.rider_status==='unassigned'&&<p className="mutedContact">Rider number will appear here after Super Admin assigns a rider.</p>}
    </div>

    <div className="customerDeliveryLocation">
     <MapPin/>
     <div><b>Your delivery location</b><small>{data.delivery_address||'Saved delivery location'}</small></div>
     <a href={mapLink(data.customer_latitude,data.customer_longitude,data.delivery_address)} target="_blank" rel="noreferrer">Open map</a>
    </div>

    <div className="orderSummary">
     <div className="row"><b>Total</b><b>AED {Number(data.total).toFixed(2)}</b></div>
     {data.items?.map((i:any,idx:number)=><div className="listRow" key={`${i.name}-${idx}`}><span>{i.qty}× {i.name}</span><span>AED {Number(i.line_total).toFixed(2)}</span></div>)}
    </div>
   </>}
  </div>
 </main>;
}
