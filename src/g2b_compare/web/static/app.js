const form=document.querySelector("#search-form");
const region=document.querySelector("#results-region");
if(form&&region){
  const loadingStates=new Set(["current-results","no-matches","stale","sync-failed-last-good"]);
  const load=async(url)=>{
    const state=region.querySelector("[data-primary-state]")?.dataset.primaryState;
    const showLoading=loadingStates.has(state);
    if(showLoading){region.setAttribute("aria-busy","true");}
    try{
      const response=await fetch(url,{headers:{"X-Requested-With":"fetch"}});
      const payload=await response.json();
      region.innerHTML=payload.html;
      history.pushState({}, "", url);
    }finally{
      if(showLoading){region.removeAttribute("aria-busy");}
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
}
