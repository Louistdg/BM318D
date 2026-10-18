/* Connector owner keeps its module unchanged. Use the existing Settings
   admin session only for same-origin connector mutations. Server still verifies
   identity and permissions; client headers do not grant authority by themselves. */
(()=>{'use strict';
const original=window.fetch.bind(window);
window.fetch=(resource,options)=>{
  const request=typeof Request!=='undefined'&&resource instanceof Request?resource:null;
  const url=new URL(request?request.url:String(resource),window.location.href);
  const method=String(options?.method||request?.method||'GET').toUpperCase();
  if(url.origin===window.location.origin&&url.pathname.startsWith('/api/mc/connectors/')&&url.pathname!=='/api/mc/connectors/list'&&method==='POST'){
    const headers=new Headers(options?.headers||request?.headers);
    const admin=(typeof window.mcJetonAdmin==='string')?window.mcJetonAdmin:'';
    if(admin&&!headers.has('X-MC-Agent-Token')&&!headers.has('X-MC-Admin')){
      headers.set('X-MC-Admin',admin);options={...options,headers};
    }
  }
  return original(resource,options);
};
})();
