import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {Search,MapPin,Store,Clock3,Bike} from 'lucide-react';
import {request} from '../api';

type Shop={id:number;name:string;slug:string;category:string;description?:string;logo_url?:string;city:string;delivery_fee:number;min_order:number;estimated_minutes:number;is_open:boolean};

export default function Marketplace(){
 const [q,setQ]=useState(''); const [shops,setShops]=useState<Shop[]>([]); const [err,setErr]=useState('');
 useEffect(()=>{const t=setTimeout(()=>{setErr('');request('/api/public/shops'+(q?`?q=${encodeURIComponent(q)}`:'')).then(setShops).catch(e=>setErr(e.message))},220);return()=>clearTimeout(t)},[q]);
 return <main className="page">
  <header className="topBrand"><Link to="/" className="brandMark"><span className="brandDot">M</span><b>Mahi Eats</b></Link><div className="topLinks"><Link to="/track/0">Track order</Link></div></header>
  <header className="hero mahiHero"><div className="eyebrow">DELIVERY ACROSS YOUR CITY</div><h1>Good food, one app.</h1><p>Search restaurants, cafes and shops. Order from one Mahi Eats app.</p><div className="search"><Search size={20}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search shop, pizza, burger, cafe..."/></div></header>
  <section><div className="sectionTitle"><h2>Restaurants & shops</h2><span>{shops.length} available</span></div>{err&&<div className="error">{err}</div>}
   <div className="shopGrid">{shops.map(s=><Link className="shopCard" to={`/shop/${s.slug}`} key={s.id}><div className="shopLogo">{s.logo_url?<img src={s.logo_url} alt={s.name}/>:<Store/>}</div><div className="shopBody"><div className="row"><h3>{s.name}</h3><span className={s.is_open?'open':'closed'}>{s.is_open?'Open':'Closed'}</span></div><p>{s.category}{s.description?` · ${s.description}`:''}</p><div className="meta"><span><MapPin size={14}/>{s.city}</span><span><Bike size={14}/>AED {s.delivery_fee.toFixed(2)}</span><span><Clock3 size={14}/>{s.estimated_minutes} min</span>{s.min_order>0&&<span>Min AED {s.min_order.toFixed(2)}</span>}</div></div></Link>)}</div>
   {shops.length===0&&!err&&<div className="empty">No active shops yet. Add the first shop from Super Admin.</div>}
  </section>
 </main>
}
