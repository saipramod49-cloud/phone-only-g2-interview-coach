export type Presentation='stream'|'complete';
export class LiveState {
  wordsPerLine=6;linesPerPage=6;charsPerLine=38;
  answer='';question='';answerId='';pending=false;lineOffset=0;
  presentation:Presentation='stream';
  private incoming='';
  get page(){return Math.floor(this.lineOffset/this.linesPerPage);}
  set page(value:number){this.lineOffset=Math.max(0,value*this.linesPerPage);}
  setPresentation(value:Presentation){this.presentation=value;if(value==='stream'&&this.pending&&this.incoming){this.answer=this.incoming;this.lineOffset=0;}}
  apply(m:{type:string;text?:string;question?:string;answer_id?:string}){
    if(m.type==='answer.start'){this.answerId=m.answer_id??'';this.question=m.question??'';this.pending=true;this.incoming='';}
    if(m.answer_id!==this.answerId)return;
    if(m.type==='answer.delta'){
      const first=!this.incoming;this.incoming+=m.text??'';
      if(this.presentation==='stream'){this.answer=this.incoming;if(first)this.lineOffset=0;}
    }
    if(m.type==='answer.done'){
      if(this.presentation==='complete')this.lineOffset=0;
      this.answer=m.text??this.incoming;this.pending=false;
    }
  }
  lines(text=this.answer||this.question||'Press Start practice on your phone.'){
    const lines:string[]=[];let line='';let count=0;
    for(const word of text.split(/\s+/))for(let i=0;i<word.length;i+=this.charsPerLine){
      const part=word.slice(i,i+this.charsPerLine);
      if(line&&((line+' '+part).trim().length>this.charsPerLine||count>=this.wordsPerLine)){lines.push(line);line='';count=0;}
      line=(line+' '+part).trim();count++;
    }
    if(line)lines.push(line);return lines.length?lines:[''];
  }
  pages(){const lines=this.lines(),pages:string[]=[];for(let i=0;i<lines.length;i+=this.linesPerPage)pages.push(lines.slice(i,i+this.linesPerPage).join('\n'));return pages;}
  scrollLines(count:number){this.lineOffset=Math.max(0,Math.min(this.lineOffset+count,Math.max(0,this.lines().length-this.linesPerPage)));}
  followLine(line:number){const target=Math.max(0,line-1);if(target>this.lineOffset)this.lineOffset=Math.min(target,Math.max(0,this.lines().length-this.linesPerPage));}
  frame(){const lines=this.lines();this.lineOffset=Math.max(0,Math.min(this.lineOffset,lines.length-1));return `${this.answer?'ANSWER':'QUESTION'}  ${this.page+1}/${this.pages().length}\n\n${lines.slice(this.lineOffset,this.lineOffset+this.linesPerPage).join('\n')}`;}
}
