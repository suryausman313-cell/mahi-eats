export const API=(import.meta.env.VITE_API_BASE_URL||'http://localhost:8000').replace(/\/$/,'');

function errorText(data:any){
 if(!data) return 'Request failed';
 const detail=data.detail;
 if(typeof detail==='string') return detail;
 if(Array.isArray(detail)) return detail.map((x:any)=>x?.msg||x?.message||JSON.stringify(x)).join(' · ');
 if(detail&&typeof detail==='object') return detail.msg||detail.message||JSON.stringify(detail);
 if(typeof data.message==='string') return data.message;
 return 'Request failed';
}

export async function request(path:string,opts:RequestInit={},token?:string){
 const headers=new Headers(opts.headers||{});
 if(!headers.has('Content-Type')) headers.set('Content-Type','application/json');
 if(token) headers.set('Authorization',`Bearer ${token}`);
 const r=await fetch(`${API}${path}`,{...opts,headers});
 const data=await r.json().catch(()=>({}));
 if(!r.ok) throw new Error(errorText(data));
 return data;
}
