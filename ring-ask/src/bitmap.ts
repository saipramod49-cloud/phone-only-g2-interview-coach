import {ImageContainerProperty,ImageRawDataUpdate,ImageRawDataUpdateResult,type EvenAppBridge} from '@evenrealities/even_hub_sdk';
import {measuredPage,readingLayout,deadline,emphasisParts} from './reader.mjs';
const canvas=document.createElement('canvas');canvas.width=576;canvas.height=288;
const ctx=canvas.getContext('2d')!;
function width(text:string,font:string){return emphasisParts(text).reduce((sum:number,part:any)=>{ctx.font=`${part.bold?'700':'400'} ${font}px Arial, sans-serif`;return sum+ctx.measureText(part.text).width;},0);}
export function bitmapPage(text:string,index:number,pref:any){return measuredPage(text,index,pref,(value:string)=>width(value,pref.font));}
export function imageContainers(){return Array.from({length:4},(_,i)=>new ImageContainerProperty({containerID:i+2,containerName:`tile${i}`,xPosition:(i%2)*288,yPosition:Math.floor(i/2)*144,width:288,height:144,zOrderIndex:i+1}));}

function drawWrapped(text:string,x:number,y:number,maxWidth:number,font:string){
  let line='',row=0;
  for(const word of text.split(/\s+/)){
    const test=line?line+' '+word:word;
    ctx.font=`${/^[A-Z][A-Z ]+(?:[—–-]|$)/.test(test)?'700':'400'} ${font}px Arial, sans-serif`;
    if(line&&ctx.measureText(test).width>maxWidth){ctx.fillText(line,x,y+row*(Number(font)+4));line=word;row++;}else line=test;
  }
  if(line)ctx.fillText(line,x,y+row*(Number(font)+4));
}
export class BitmapDisplay{
 private sent:string[]=[];
 reset(){this.sent=[];}
 async paintSplit(bridge:EvenAppBridge,left:string,right:string,font:string,pref:any){
  const box=readingLayout(pref),gap=8,half=Math.floor((box.width-gap)/2);
  ctx.fillStyle='#000';ctx.fillRect(0,0,576,288);ctx.fillStyle='#fff';ctx.textBaseline='top';ctx.strokeStyle='#fff';ctx.lineWidth=1;
  ctx.strokeRect(box.x+.5,box.y+.5,half-1,box.height-1);ctx.strokeRect(box.x+half+gap+.5,box.y+.5,box.width-half-gap-1,box.height-1);
  drawWrapped(left,box.x+7,box.y+5,half-14,font);drawWrapped(right,box.x+half+gap+7,box.y+5,box.width-half-gap-14,font);
  await this.send(bridge);
 }
 async paint(bridge:EvenAppBridge,text:string,font:string,pref:any){
  const box=readingLayout(pref);
  ctx.fillStyle='#000';ctx.fillRect(0,0,576,288);ctx.fillStyle='#fff';ctx.font=`${font}px Arial, sans-serif`;ctx.textBaseline='top';
  ctx.strokeStyle='#fff';ctx.lineWidth=1;ctx.strokeRect(box.x+.5,box.y+.5,box.width-1,box.height-1);
  text.split('\n').forEach((line,i)=>{const y=box.y+4+i*(Number(font)+4);if(line==='---'){ctx.beginPath();ctx.moveTo(box.x+8,y+Number(font)/2);ctx.lineTo(box.x+box.width-8,y+Number(font)/2);ctx.stroke();}else{let x=box.x+8;for(const part of emphasisParts(line)){ctx.font=`${part.bold?'700':'400'} ${font}px Arial, sans-serif`;ctx.fillText(part.text,x,y);x+=ctx.measureText(part.text).width;}}});
  await this.send(bridge);
 }
 private async send(bridge:EvenAppBridge){
  const tiles=Array.from({length:4},(_,i)=>{const tile=document.createElement('canvas');tile.width=288;tile.height=144;tile.getContext('2d')!.drawImage(canvas,(i%2)*288,Math.floor(i/2)*144,288,144,0,0,288,144);return tile.toDataURL('image/png');});
  for(let i=0;i<4;i++){
   if(this.sent[i]===tiles[i])continue;
   const bytes=Uint8Array.from(atob(tiles[i].split(',')[1]),c=>c.charCodeAt(0));
   const result=await deadline(bridge.updateImageRawData(new ImageRawDataUpdate({containerID:i+2,containerName:`tile${i}`,imageData:bytes})),6500);
   if(result!==ImageRawDataUpdateResult.success)throw new Error('Font display update failed. Select Native font to retry.');
   this.sent[i]=tiles[i];
  }
 }
}
