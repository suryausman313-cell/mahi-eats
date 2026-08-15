export const API=(import.meta.env.VITE_API_BASE_URL||'http://localhost:8000').replace(/\/$/,'');
export async function request(path:string,opts:RequestInit={},token?:string){
 const headers=new Headers(opts.headers||{}); headers.set('Content-Type','application/json'); if(token) headers.set('Authorization',`Bearer ${token}`);
 const r=await fetch(`${API}${path}`,{...opts,headers}); const data=await r.json().catch(()=>({})); if(!r.ok) throw new Error(data.detail||'Request failed'); return data;
}
