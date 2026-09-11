export type SavedProfile={values:Record<string,string|boolean>;model:{model:string;reasoning_effort:string};instructions:string;display:Record<string,unknown>};
export class ProfileMemory {
 private key:string;
 constructor(private storage:Pick<Storage,'getItem'|'setItem'|'removeItem'>,host:string){this.key='coach-profile-v2:'+host;}
 private data():{last:string;token:string;profiles:Record<string,SavedProfile>}{
  try{const value=JSON.parse(this.storage.getItem(this.key)??'null');if(value&&typeof value.last==='string'&&typeof value.token==='string'&&value.profiles&&typeof value.profiles==='object')return value;}catch{}
  return {last:'',token:'',profiles:{}};
 }
 last(){return this.data().last;}
 token(){return this.data().token;}
 load(id:string){const p=this.data().profiles[id];return p&&p.values&&typeof p.values==='object'&&!Array.isArray(p.values)&&p.model&&typeof p.model==='object'&&typeof p.instructions==='string'&&p.display&&typeof p.display==='object'?p:undefined;}
 save(id:string,profile:SavedProfile,token:string,remember:boolean){const data=this.data();data.last=id;data.profiles[id]=profile;data.token=remember?token:'';this.storage.setItem(this.key,JSON.stringify(data));}
 forget(){this.storage.removeItem(this.key);}
}
