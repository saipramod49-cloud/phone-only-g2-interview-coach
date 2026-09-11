export const ringActions = [
 ['listen', 'Listen / next question'], ['finish', 'Finish question'],
 ['pause', 'Pause microphone'], ['retry', 'Retry last answer'],
 ['reconnect', 'Reconnect + listen'], ['back', 'Back to answer'],
 ['follow','Voice follow / manual'], ['candidate','Candidate speaking'],
 ['interviewer','Interviewer speaking'], ['device','Automatic speakers'],
] as const;
export class RingMenu {
 open=false; index=0;
 move(direction:number){this.index=(this.index+direction+ringActions.length)%ringActions.length;}
 tap(){if(!this.open){this.open=true;this.index=0;return null;}const action=ringActions[this.index][0];this.open=false;return action;}
 back(){if(!this.open)return false;this.open=false;return true;}
 frame(){const start=Math.floor(this.index/4)*4;return `ACTIONS ${this.index+1}/${ringActions.length}\n\n`+ringActions.slice(start,start+4).map((a,i)=>(start+i===this.index?'> ':'  ')+a[1]).join('\n');}
}
