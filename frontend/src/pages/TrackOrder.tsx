import {useEffect,useState} from 'react';
import {Link,useParams,useSearchParams} from 'react-router-dom';
import {ArrowLeft,Bike,ChefHat,CheckCircle2,MapPin,PackageCheck,Phone,Store} from 'lucide-react';
import {request} from '../api';

const kitchenSteps=['new','accepted','preparing','ready','delivered'];
const labels:any={new:'Order placed',accepted:'Accepted',preparing:'Preparing',ready:'Ready for pickup',delivered:'Delivered',cancelled:'Cancelled'};
const riderLabels:any={unassigned:'Waiting for rider',assigned:'Rider assigned',accepted:'Rider accepted',picked_up:'Picked up',on_the_way:'On the way',delivered:'Delivered',cancelled:'Cancelled'};

export default function TrackOrder(){
 const {orderId}=useParams(); const [sp]=useSearchParams(); const [phone,setPhone]=useState(sp.get('phone')||localStorage.getItem(`track_phone_${orderId}`)||''); const [data,setData]=useState<any>(null); const [msg,setMsg]=useState('');
 async function load(){if(!orderId||orderId==='0'||!phone)return;try{const r=await request(`/api/public/orders/${orderId}?phone=${encodeURIComponent(phone)}`);setData(r);setMsg('');localStorage.setItem(`track_phone_${orderId}`,phone)}catch(e:any){setMsg(e.message)}}
 useEffect(()=>{load();const t=setInterval(load,5000);return()=>clearInterval(t)},[orderId,phone]);
 if(orderId==='0')return <main className="auth"><div className="panel"><h1>Track an order</h1><p>Open the tracking link shown after checkout, or enter the order URL and phone.</p><Link className="buttonLink" to="/">Back to Mahi Eats</Link></div></main>;
 return <main className="page narrow"><Link className="back" to="/"><ArrowLeft size={18}/>Mahi Eats</Link><div className="panel"><div className="eyebrow">LIVE ORDER TRACKING</div><h1>Order #{orderId}</h1>{!phone&&<><p>Enter the phone number used on this order.</p><input value={phone} onChange={e=>setPhone(e.target.value)} placeholder="Phone number"/></>}{msg&&<div className="error">{msg}</div>}
 {data&&<><div className="trackingShop"><Store/><div><b>{data.shop?.name}</b><small>{data.shop?.address||''}</small></div></div><div className="timeline">{kitchenSteps.map((s,i)=>{const current=kitchenSteps.indexOf(data.status);const done=current>=i&&data.status!=='cancelled';return <div className={done?'step done':'step'} key={s}><span>{done?<CheckCircle2/>:<ChefHat/>}</span><b>{labels[s]}</b></div>})}</div>
 <div className="deliveryCard"><div className="row"><h2><Bike/> Delivery</h2><b>{data.delivery_mode==='mahi_eats'?'Mahi Eats':'Shop delivery'}</b></div><p className="statusBig">{riderLabels[data.rider_status]||data.rider_status}</p>{data.rider&&<div className="riderInfo">{data.rider.photo_url?<img src={data.rider.photo_url}/>:<Bike/>}<div><b>{data.rider.name}</b><a href={`tel:${data.rider.phone}`}><Phone size={14}/>{data.rider.phone}</a>{data.rider.latitude!=null&&<span><MapPin size={14}/>Live: {Number(data.rider.latitude).toFixed(5)}, {Number(data.rider.longitude).toFixed(5)}</span>}</div></div>}{!data.rider&&data.merchant_rider_name&&<div className="riderInfo"><PackageCheck/><div><b>{data.merchant_rider_name}</b><a href={`tel:${data.merchant_rider_phone}`}><Phone size={14}/>{data.merchant_rider_phone}</a></div></div>}</div>
 <div className="orderSummary"><div className="row"><b>Total</b><b>AED {Number(data.total).toFixed(2)}</b></div>{data.items?.map((i:any)=><div className="listRow" key={i.name}><span>{i.qty}× {i.name}</span><span>AED {Number(i.line_total).toFixed(2)}</span></div>)}</div></>}
 </div></main>
}
