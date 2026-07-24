const form=document.querySelector("#search-form");
const region=document.querySelector("#results-region");
if(form&&region){
  const load=async(url)=>{
    region.setAttribute("aria-busy","true");
    try{
      const response=await fetch(url,{headers:{"X-Requested-With":"fetch"}});
      const payload=await response.json();
      region.innerHTML=payload.html;
      history.pushState({}, "", url);
    }finally{
      region.removeAttribute("aria-busy");
    }
  };
  form.addEventListener("submit",(event)=>{
    event.preventDefault();
    const url=new URL(form.action,location.href);
    url.search=new URLSearchParams(new FormData(form)).toString();
    void load(url);
  });
  region.addEventListener("click",(event)=>{
    const target=event.target;
    if(!(target instanceof Element)){return;}
    const link=target.closest(".next-page,.previous-page,.category-choice");
    if(link instanceof HTMLAnchorElement){
      event.preventDefault();
      void load(new URL(link.href,location.href));
      return;
    }
    const copy=target.closest(".copy-id");
    if(copy instanceof HTMLElement){
      const value=copy.dataset.copyId;
      if(value){void navigator.clipboard.writeText(value);}
    }
  });
  region.addEventListener("error",(event)=>{
    const target=event.target;
    if(target instanceof HTMLImageElement&&target.closest(".product-image")){
      target.hidden=true;
    }
  },true);
}
