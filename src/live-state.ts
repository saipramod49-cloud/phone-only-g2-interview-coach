export class LiveState {
  wordsPerLine = 6;
  linesPerPage = 6;
  charsPerLine = 38;
  answer = '';
  question = '';
  answerId = '';
  pending = false;
  page = 0;
  apply(m: {type: string; text?: string; question?: string; answer_id?: string}) {
    if (m.type === 'answer.start') {
      this.answerId = m.answer_id ?? ''; this.question = m.question ?? '';
      this.pending = true;
      // Keep previous answer until the first token of the new answer arrives.
    }
    if (m.type === 'answer.delta' && m.answer_id === this.answerId) {
      if(this.pending){this.answer = ''; this.page = 0; this.pending = false;}
      this.answer += m.text ?? '';
    }
    if (m.type === 'answer.done' && m.answer_id === this.answerId && m.text) {
      this.answer = m.text; this.pending = false;
    }
  }
  pages() {
    const lines: string[] = []; let line = ''; let count = 0;
    for(const word of (this.answer || this.question || 'Press Start practice on your phone.').split(/\s+/)) {
      for(let i=0;i<word.length;i+=this.charsPerLine){
        const part=word.slice(i,i+this.charsPerLine);
        if(line && ((line+' '+part).trim().length>this.charsPerLine || count>=this.wordsPerLine)){lines.push(line);line='';count=0;}
        line=(line+' '+part).trim();count++;
      }
    }
    if(line)lines.push(line);
    const pages: string[]=[];
    for(let i=0;i<lines.length;i+=this.linesPerPage)pages.push(lines.slice(i,i+this.linesPerPage).join('\n'));
    return pages;
  }
  frame(){const pages=this.pages();this.page=Math.max(0,Math.min(this.page,pages.length-1));return `${this.answer?'ANSWER':'QUESTION'}  ${this.page+1}/${pages.length}\n\n${pages[this.page]}`;}
}
