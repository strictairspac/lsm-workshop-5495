import{listSites}from'../api/quota.js';
export const quota={sites:[],currentId:null,async loadSites(){this.sites=await listSites();if(!this.currentId&&this.sites.length)this.currentId=this.sites[0].id;return this.sites},select(id){this.currentId=Number(id)},current(){return this.sites.find(s=>s.id===this.currentId)||null}};
