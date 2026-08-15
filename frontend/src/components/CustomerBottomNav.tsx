import {Home,UtensilsCrossed,ShoppingBag,ReceiptText,UserRound} from 'lucide-react';
import {Link,useNavigate} from 'react-router-dom';

type CustomerNavKey='home'|'menu'|'cart'|'orders'|'account';

type Props={
 active?:CustomerNavKey;
 onMenu?:()=>void;
 onCart?:()=>void;
 cartCount?:number;
};

export default function CustomerBottomNav({active,onMenu,onCart,cartCount=0}:Props){
 const nav=useNavigate();
 function openLastShop(mode:'menu'|'cart'){
  const slug=localStorage.getItem('mahi_last_shop_slug')||'';
  if(!slug){nav('/');return}
  nav(`/shop/${encodeURIComponent(slug)}${mode==='cart'?'?cart=1':'?menu=1'}`);
 }
 return <nav className="customerBottomNav" aria-label="Customer navigation">
  <Link className={active==='home'?'active':''} to="/"><Home/><span>Home</span></Link>
  <button className={active==='menu'?'active':''} type="button" onClick={onMenu||(()=>openLastShop('menu'))}><UtensilsCrossed/><span>Menu</span></button>
  <button className={active==='cart'?'active':''} type="button" onClick={onCart||(()=>openLastShop('cart'))}><span className="navIconWrap"><ShoppingBag/>{cartCount>0&&<b className="navCartBadge">{cartCount>99?'99+':cartCount}</b>}</span><span>Cart</span></button>
  <Link className={active==='orders'?'active':''} to="/orders"><ReceiptText/><span>Orders</span></Link>
  <Link className={active==='account'?'active':''} to="/account"><UserRound/><span>Account</span></Link>
 </nav>
}
