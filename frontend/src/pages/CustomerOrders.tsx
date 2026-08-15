import {useEffect,useState} from 'react';
import {Link,useNavigate} from 'react-router-dom';
import {ArrowLeft,Clock3,MapPin,ReceiptText,Store} from 'lucide-react';
import {request} from '../api';

export default function CustomerOrders(){
 const nav=useNavigate(); const token=localStorage.getItem('customer_token')||''; const [orders,setOrders]=useState<any[]>([]); const [msg,setMsg]=useState('');
 useEffect(()=>{if(!token){nav('/account?return=/orders');return}request('/api/customer/orders',{},token).then(setOrders).catch(e=>setMsg(e.message))},[]);
 return <main className="page customerOrdersPage"><div className="row"><div><Link className="back" to="/"><ArrowLeft/>Home</Link><div className="eyebrow">YOUR MAHI EATS</div><h1>Orders</h1></div><Link className="buttonLink secondary" to="/account">Account</Link></div>{msg&&<div className="error">{msg}</div>}<div className="customerOrderList">{orders.map(o=><article className="customerOrderCard" key={o.id}><div className="customerOrderTop"><div className="miniLogo"><Store/></div><div><h3>{o.shop?.name||'Shop'}</h3><span>Order #{o.id}</span></div><span className={`statusPill ${o.status}`}>{o.status}</span></div><div className="customerOrderMeta"><span><Clock3/> {new Date(o.created_at).toLocaleString('en-AE',{timeZone:'Asia/Dubai'})}</span><span><MapPin/> {o.delivery_address||'Delivery address'}</span></div><div className="row"><b>AED {Number(o.total||0).toFixed(2)}</b><Link className="small buttonLink" to={`/track/${o.id}?phone=${encodeURIComponent(o.customer_phone)}`}>View details</Link></div></article>)}{!orders.length&&!msg&&<div className="marketEmpty"><ReceiptText/><h3>No orders yet</h3><p>Your Mahi Eats orders will appear here.</p><Link className="buttonLink" to="/">Browse shops</Link></div>}</div></main>;
}
