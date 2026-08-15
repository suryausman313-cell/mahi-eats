import {Routes,Route} from 'react-router-dom';
import Marketplace from './pages/Marketplace';
import ShopPage from './pages/ShopPage';
import TrackOrder from './pages/TrackOrder';
import SuperAdmin from './pages/SuperAdmin';
import ShopAdmin from './pages/ShopAdmin';
import Kitchen from './pages/Kitchen';
import Rider from './pages/Rider';

export default function App(){
 return <Routes>
  <Route path="/" element={<Marketplace/>}/>
  <Route path="/shop/:slug" element={<ShopPage/>}/>
  <Route path="/track/:orderId" element={<TrackOrder/>}/>
  <Route path="/super-admin" element={<SuperAdmin/>}/>
  <Route path="/shop-admin" element={<ShopAdmin/>}/>
  <Route path="/kitchen" element={<Kitchen/>}/>
  <Route path="/rider" element={<Rider/>}/>
 </Routes>
}
